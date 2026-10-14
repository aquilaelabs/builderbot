// What the page has said: a toast for the moment, and the bell, which
// keeps the last fifty and what waits on this account (a session's ask, a
// held change).
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- toasts -------------------------------------------------------------

let toastTimer = null;
// How bad is it: "info", "warn" or "bad". The second argument was a boolean
// and sixty-odd callers pass `true` for a failure, so `true` still means what
// it always did and "warn" is the new middle: a caller that never learns
// about it keeps working and keeps meaning the same thing.
function level(v){
  return v === true || v === "bad" ? "bad" : v === "warn" ? "warn" : "info";
}

function notify(msg, bad){
  const lv = level(bad);
  const el = $("toast");
  el.textContent = msg;
  el.classList.toggle("bad", lv === "bad");
  el.classList.toggle("warn", lv === "warn");
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"),
                          lv === "info" ? 4000 : 7000);
  logNote(msg, bad);
}

// ---- what the page has said, and what is waiting on you ----------------

// A toast says a thing once, for four seconds, to whoever happened to be
// looking. That is the right deal for "saved" and the wrong one for every
// message that matters: a failure you were not at the screen for did not
// happen, as far as you can tell afterwards. So every notify() lands here as
// well and stays until it is cleared.
//
// It is a page-lifetime log, deliberately: these are things this tab said,
// and a reload is a fair line to draw under them. What is NOT from here is
// the asks: a session blocked on the phone is the server's fact, read live,
// so it leaves the list the moment it is answered or times out rather than
// sitting there as a record of a decision already made.
const NOTE_CAP = 50;
let notes = [], notesSeen = 0, bellOpen = false;
// The red things the bell has already flashed for, by identity, so a new
// one flashes it twice and a redraw of the same one does not (the operator,
// 11 Oct). null until the first draw, which flashes nothing: a reload is
// not news.
let bellRedSeen = null;

function logNote(msg, bad){
  // `bad` is kept beside `lv` because the row's own styling and every test
  // that reads it predate the third level; lv is what the dot is chosen from.
  notes.unshift({msg: String(msg), bad: level(bad) === "bad",
                 lv: level(bad), at: Date.now()});
  if (notes.length > NOTE_CAP) notes.length = NOTE_CAP;
  drawBell();
}

// One row of what needs doing on a node, in the drawer's quiet shape: a
// title in ink, one line of what, the one thing to know before acting said
// on the row, the long part (every version, every project) folded, and the
// way there and Dismiss on the row. Out of window is red and cannot be put
// away: work there is stopped until it is updated.
function attRow(a){
  if (a.kind === "toolchain"){
    const keys = a.tools.map(t => t.key).filter(Boolean).join(" ");
    const cc = a.tools.some(t => t.name === "claude-code") && a.projects.length;
    const n = a.tools.length;
    return `<div class="bnote att">
      <div class="bt">${n} toolchain update${n === 1 ? "" : "s"} on ${esc(a.node)}</div>
      <div class="bsum">${a.tools.map(t => esc(t.label)).join(", ")}</div>
      ${cc ? `<div class="bwarn">Updating Claude Code ends the Claude sessions there
        (${a.projects.length} project${a.projects.length === 1 ? "" : "s"})</div>` : ""}
      <details class="bdetail"${sectAttr("bell:tc:" + a.id)}><summary>versions${cc ? " and projects" : ""}</summary><pre>${
        a.tools.map(t => `${esc(t.label)}: ${esc(t.from || "?")} → ${t.to === "newer" ? "a newer version" : esc(t.to)}`).join("\n")}${
        cc ? `\n\nsessions there: ${a.projects.map(esc).join(", ")}` : ""}</pre></details>
      <div class="bfoot"><span>on its Toolchains tab</span>
        <span class="acts">${keys ? `<a href="#" data-bdismiss="${esc(keys)}">Dismiss</a>` : ""}
          <a href="#" data-btc="${esc(a.id)}">Toolchains tab</a></span></div></div>`;
  }
  // A copy or move that did not happen: the reason, which used to sit on
  // the container's row for ever, here where it can be put away.
  if (a.kind === "relocate"){
    return `<div class="bnote att bad">
      <div class="bt">Copying or moving ${esc(a.name)} did not happen</div>
      <div class="bsum">${esc(a.why)}</div>
      <div class="bfoot"><span>${a.at ? esc(ago(a.at)) : "on the Docker tab"}</span>
        <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
          <a href="#" data-bdocker="${esc(a.node_id)}">Docker tab</a></span></div></div>`;
  }
  // A container whose registry image moved (R195): one note per node, to
  // the Docker tab on that node, where Update is on each row.
  if (a.kind === "image"){
    const n = a.containers.length;
    return `<div class="bnote att">
      <div class="bt">${n} container update${n === 1 ? "" : "s"} on ${esc(a.node)}</div>
      <div class="bsum">${a.containers.map(c => `${esc(c.name)} (${c.images.map(esc).join(", ")})`).join(", ")}</div>
      <div class="bfoot"><span>on its Docker tab</span>
        <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
          <a href="#" data-bdocker="${esc(a.id)}">Docker tab</a></span></div></div>`;
  }
  // A node's nginx behind the newest line (R192): its own note, to the
  // nginx tab on that node, where Update is.
  if (a.kind === "nginx"){
    return `<div class="bnote att">
      <div class="bt">nginx update on ${esc(a.node)}</div>
      <div class="bsum">runs ${esc(a.from)} and ${esc(a.to)} is out</div>
      <div class="bfoot"><span>on its nginx tab</span>
        <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
          <a href="#" data-bnginx="${esc(a.id)}">nginx tab</a></span></div></div>`;
  }
  return `<div class="bnote att${a.window ? " bad" : ""}">
    <div class="bt">${a.window ? `${esc(a.node)}'s agent is out of window` : `Agent update on ${esc(a.node)}`}</div>
    <div class="bsum">runs agent ${esc(a.from)} and this controller ships ${esc(a.to)}${a.window
      ? `: ${a.projects.length ? `${a.projects.length} project${a.projects.length === 1 ? "" : "s"} cannot build, test or use the emulator there`
                               : "nothing works there"} until it is updated` : ""}</div>
    ${a.window && a.projects.length ? `<details class="bdetail"${sectAttr("bell:agent:" + a.id)}><summary>projects</summary><pre>${
      a.projects.map(esc).join(", ")}</pre></details>` : ""}
    <div class="bfoot"><span>${a.window ? "work on it is stopped" : "on the Nodes tab"}</span>
      <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
        <a href="#" data-bnode="${esc(a.id)}" data-bwhat="agent">Nodes tab</a></span></div></div>`;
}

// What needs doing that is not a question, as rows: the bell's "Needs
// attention" group and Home's Attention card (R218 step 5) draw the same
// ones. From the poll, never stored here, so a row leaves the moment it
// stops being true.
function needsRows(){
  const att = state?.attention || [], ciRed = state?.ci_red || [], syncC = state?.sync_conflicts || [];
  // What needs doing but is not a question: a node behind, a red CI run, a
  // file changed in two places. One quiet shape (attRow): a title, one line
  // of what, the action on the row, the long part folded (the operator,
  // 10 Oct: the amber wall of versions and project names).
  return [
    // ...and the nodes. Out of window is red and names the projects it
    // stops; behind is amber and waits for a press on the Nodes tab.
    // A window move holds every project at once, so several of these is the
    // normal case after a minor bump and one row per project was six rows
    // saying one thing. Collapsed into one, with one press behind it (B93).
    ...att.map(attRow),
    ...ciRed.map(c => `<div class="bnote att bad">
        <div class="bt">CI failing in ${esc(projLabel(c.project))}</div>
        <div class="bsum">${esc(c.text)}</div>
        <div class="bfoot"><span>until the check passes again</span>
          <span class="acts">${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">On GitHub</a>` : ""}
            <a href="#" data-bci="${esc(c.project)}">Git view</a></span></div></div>`),
    ...syncC.map(c => `<div class="bnote att">
        <div class="bt">Changed in two places: ${esc(projLabel(c.project))}</div>
        <div class="bsum">${esc(c.path)} was changed on ${esc(c.node)} after another copy had changed it; that version is kept as ${esc(c.kept_as)}</div>
        <div class="bfoot"><span>until that copy is deleted · ${esc(ago(c.at))}</span></div></div>`),
  ];
}

function drawBell(){
  const bell = $("bBell"), panel = $("bellPanel");
  if (!bell) return;
  const asks = ph?.asks || [];
  // Invitations to a project waiting on this account (membership.py): its
  // own answer, Accept or Decline, from the poll like the rest.
  const invites = state?.invites || [];
  // What sessions have waiting for approval, per project (roadmap #27):
  // the server's fact like an ask, so it leaves the moment it is answered.
  const waiting = (state?.projects || []).filter(p => p.pending > 0);
  // What the nodes need: an agent behind, or from another window. From the
  // poll, never stored here, so a row leaves the moment it stops being true.
  const att = state?.attention || [];
  // A project whose main branch's newest CI run failed (R117): from the
  // poll, so it leaves when a run passes.
  const ciRed = state?.ci_red || [];
  // A file changed on two synced copies at once (R162): listed until the
  // copy kept beside it is deleted.
  const syncC = state?.sync_conflicts || [];
  const unread = Math.max(0, notes.length - notesSeen);
  // The WORST of what is unread, not the newest. notes are unshifted, so the
  // first `unread` of them are the new ones. A failure followed by three
  // "saved"s is still a failure nobody has looked at.
  const fresh = notes.slice(0, unread);
  const worst = fresh.some(n => n.lv === "bad") ? "bad"
              : fresh.some(n => n.lv === "warn") ? "warn"
              : fresh.length ? "info" : "";
  const dot = bell.querySelector(".dot");
  const pendingOn = asks.length + waiting.length + invites.length;
  const attOn = att.some(a => a.window || a.kind === "relocate") || ciRed.length ? "bad" : att.length + syncC.length ? "warn" : "";
  // Something new gone wrong: the bell flashes red twice and settles to the
  // red dot, unlike an ask's amber, which keeps on until it is answered.
  const red = new Set([
    ...fresh.filter(n => n.lv === "bad").map(n => "note:" + n.at + ":" + n.msg),
    ...att.filter(a => a.window || a.kind === "relocate").map(a => "att:" + (a.key || a.id + "@" + (a.at || a.to || ""))),
    ...ciRed.map(c => "ci:" + JSON.stringify(c))]);
  if (bellRedSeen !== null && [...red].some(k => !bellRedSeen.has(k)) && !noMotion()){
    bell.classList.remove("flash");
    void bell.offsetWidth;            // restart it when it is already running
    bell.classList.add("flash");
    // Off again when done, or it would sit over an ask's amber later.
    bell.addEventListener("animationend", e => { if (e.animationName === "bellbad") bell.classList.remove("flash"); }, {once: true});
  }
  bellRedSeen = red;
  dot.hidden = !(pendingOn || att.length || ciRed.length || syncC.length || unread);
  // An ask outranks every level of record: one is a thing that happened, the
  // other is a thing that has not happened yet because it is waiting on you.
  // A node alert sits between: red when work is stopped, amber when an
  // update merely waits.
  dot.className = "dot" + (pendingOn ? " ask" : attOn ? " " + attOn : worst ? " " + worst : "");
  bell.classList.toggle("has", !!(pendingOn || att.length || ciRed.length || syncC.length || unread));
  bell.classList.toggle("waiting", pendingOn > 0);
  bell.title = pendingOn
    ? `${pendingOn} waiting on an answer`
    : att.length + ciRed.length + syncC.length
      ? `${att.length + ciRed.length + syncC.length} need${att.length + ciRed.length + syncC.length === 1 ? "s" : ""} attention`
    : unread ? `${unread} new` : "notifications";
  // Drawn whenever it is ON SCREEN, which is the question that matters, and
  // not when a flag says it is open; those two disagreed and the panel a
  // reader was looking at stopped updating.
  if (panel.hidden) return;
  const when = t => fmtTime(t, {hour: "2-digit", minute: "2-digit"});
  const answer = [
    // Above everything the page merely said: somebody is blocked on these.
    // A root ask (roadmap R38) is the same row with the stakes said: which
    // machine, and that it is root there. `#` is the prompt root gets.
    // A removal from a release takes something away from the people
    // downloading, so it wears the destructive color, as root does.
    ...asks.map(a => `<div class="bnote ask${a.kind === "root" || a.kind === "release-remove" ? " bad" : ""}">
        <div class="btag">${
          a.kind === "root" ? `root on ${esc(a.node_name)}: needs your answer`
          : a.kind === "rebuild" ? `${esc(askVerb(a))} in ${esc(a.project ? projLabel(a.project) : "a project")}: needs your answer`
          : a.kind === "container" ? `container ${esc(a.name || "")} on ${esc(a.node_name || "the default node")}: needs your answer`
          : a.kind === "sign" ? `sign a build of ${esc(a.project ? projLabel(a.project) : "a project")}: needs your answer`
          : a.kind === "sign-key" ? `a signing key change in ${esc(a.project ? projLabel(a.project) : "a project")}: needs your answer`
          : a.kind === "release" ? `release ${esc(a.project ? projLabel(a.project) : "a project")} ${esc(a.tag || "")}: needs your answer`
          : a.kind === "release-edit" ? `edit the ${esc(a.tag || "")} release of ${esc(a.project ? projLabel(a.project) : "a project")}: needs your answer`
          : a.kind === "release-remove" ? `remove files from the ${esc(a.tag || "")} release of ${esc(a.project ? projLabel(a.project) : "a project")}: needs your answer`
          : a.kind === "phone-use" ? `your phone, from ${esc(a.project ? projLabel(a.project) : "a project")}: needs your answer`
          : a.kind === "push" ? `a push from ${esc(a.project ? projLabel(a.project) : "a project")} looks sensitive: needs your answer`
          : "needs your answer"}</div>
        <div class="bwhy">${esc(a.why)}</div>
        <div class="bcmd">${a.kind === "root" ? "# " : a.kind === "phone-use" ? "" : a.kind === "rebuild" || a.kind === "container" || a.kind === "sign" || a.kind === "sign-key" || a.kind === "release" || a.kind === "release-edit" || a.kind === "release-remove" || a.kind === "push" ? "bb " : "adb "}${esc(a.cmd.join(" "))}</div>${
        // A push (R219) is approved by reading the lines that look like a
        // secret or something private, whole, open, each with its file and
        // line: Approve sends them and okays these exact lines.
        a.kind === "push" ? `<details class="bdetail" open><summary>the ${a.count || ""} flagged line${a.count === 1 ? "" : "s"}: approving okays these exact lines until they change</summary><pre class="bflag">${
            esc(a.detail || "")}</pre></details>` : ""}${
        // A container is approved by reading its compose file, the way root
        // is approved by reading its argv (R71): the file is the request, so
        // it is here whole, folded, with the env file's keys and never its
        // values, which is where a token would be.
        a.kind === "container" ? `<details class="bdetail"${sectAttr("bell:detail:" + a.id)}><summary>the compose file${
            a.env_keys?.length ? `, and an env file setting ${a.env_keys.map(esc).join(", ")}` : ""}${
            a.for ? `, for ${esc(a.for)}` : ""}</summary><pre>${esc(a.detail || "")}</pre></details>` : ""}${
        // An edit of a release (R139) is approved by reading the notes it
        // would put on the page, whole.
        a.kind === "release-edit" && a.detail ? `<details class="bdetail"${sectAttr("bell:detail:" + a.id)}><summary>the new notes</summary><pre>${
            esc(a.detail)}</pre></details>` : ""}
        <div class="bfoot"><span>${a.asker ? esc(a.asker) + "'s session · " : ""}${a.left > 60
          ? `${Math.floor(a.left / 60)} min left to answer`
          : `${a.left}s left to answer`}</span>
          <span class="acts"><a href="#" data-bdeny="${a.id}">Deny</a>${
            // A phone's commands come one after another: the second answer
            // lets the rest from this session run without asking (the
            // operator, 4 Oct), taken back on the Phone tab.
            a.kind === "phone" || a.kind === "phone-use"
              ? `<a href="#" data-ballow="${a.id}" data-bsession="1">Approve for this session</a>` : ""}
            <a href="#" data-ballow="${a.id}">Approve</a></span></div></div>`),
    ...invites.map(i => `<div class="bnote ask">
        <div class="btag">${i.kind === "owner" ? `${esc(projLabel(i.project))} offered to you` : `invited to ${esc(projLabel(i.project))}`}</div>
        <div class="bwhy">${i.kind === "owner"
          ? `${esc(i.by || "Somebody")} offers you ownership of ${esc(projLabel(i.project))}`
          : `${esc(i.by || "Somebody")} invited you to work on ${esc(projLabel(i.project))}${
              i.role ? ` as ${esc(i.role)}` : ""}`}</div>
        <div class="bfoot"><span>${esc(ago(i.at))}</span>
          <span class="acts"><a href="#" data-binvite="${i.id}" data-yes="0">Decline</a>
            <a href="#" data-binvite="${i.id}" data-yes="1">Accept</a></span></div></div>`),
    // ...and beside them, what a session has waiting in each project's
    // notebook. One row per project, not per change: the notebook is where
    // the changes are read, so the row's only job is to take you there.
    ...waiting.map(p => `<div class="bnote ask">
        <div class="btag">waiting for your approval</div>
        <div class="bwhy">${p.pending} change${p.pending === 1 ? "" : "s"} from a session in ${esc(projLabel(p.name))}</div>
        <div class="bfoot"><span>on the notebook</span>
          <span class="acts"><a href="#" data-bpend="${esc(p.name)}">Review</a></span></div></div>`),
  ];
  const needs = needsRows();
  const said = notes.map(n => `<div class="bnote${n.lv === "info" ? "" : " " + n.lv}">
        <div class="bwhy">${esc(n.msg)}</div>
        <div class="bfoot"><span>${when(n.at)}</span></div></div>`);
  // Three groups, each headed with its count, so what waits on an answer is
  // never under what the page merely said; Clear heads the one it clears.
  const hidden = state?.bell_hidden || 0;
  const group = (title, list, extra = "") => list.length
    ? `<div class="bgroup"><span>${title} · ${list.length}</span>${extra}</div>` + list.join("") : "";
  const putAway = hidden ? `<div class="bfootbar"><span>${hidden} update${hidden === 1 ? "" : "s"} dismissed</span>
      <button type="button" id="bellRestore">Show again</button></div>` : "";
  panel.innerHTML = (answer.length + needs.length + said.length
    ? group("Waiting on you", answer) + group("Needs attention", needs)
      + group("Recent", said, `<button type="button" id="bellClear">Clear</button>`)
    : `<div class="bempty">nothing to report</div>`) + putAway;
  // Any press in the drawer closes it, after the press's own handler has
  // run (the operator, 7 Oct): Approve, Deny, an invitation's answer, Clear,
  // a link to where a row is about. One listener on the drawer, so a row
  // added later is covered without remembering to.
  panel.onclick = e => {
    // ...except Dismiss and Show again, which change the drawer itself and
    // are pressed several in a row.
    if (e.target.closest?.("button, a") && !e.target.closest("[data-bdismiss], #bellRestore"))
      queueMicrotask(() => toggleBell(false));
  };
  const clear = $("bellClear");
  // Only the page's own log clears: an ask is not this button's to dismiss.
  if (clear) clear.onclick = () => { notes = []; notesSeen = 0; drawBell(); };
  panel.querySelectorAll("[data-ballow]").forEach(a => a.onclick = e => {
    e.preventDefault();
    phBusy = "running it"; phRev++; drawPanes();
    phFetch({action: "allow", id: Number(a.dataset.ballow), session: !!a.dataset.bsession});
  });
  panel.querySelectorAll("[data-bdeny]").forEach(a => a.onclick = e => {
    e.preventDefault();
    phFetch({action: "deny", id: Number(a.dataset.bdeny)});
  });
  panel.querySelectorAll("[data-binvite]").forEach(a => a.onclick = async e => {
    e.preventDefault();
    const yes = a.dataset.yes === "1";
    const j = await (await postJSON("/api/members", {action: yes ? "accept" : "decline",
                                                     id: Number(a.dataset.binvite)})).json().catch(() => ({}));
    notify(j.error || (yes ? (j.owner ? `you own ${projLabel(j.project)} now` : `you are on ${projLabel(j.project)} now`)
                           : `declined ${projLabel(j.project)}`), !!j.error);
    refresh();
  });
  panel.querySelectorAll("[data-bpend]").forEach(a => a.onclick = e => {
    e.preventDefault();
    toggleBell(false);
    openNotebook(a.dataset.bpend);
    openPending(a.dataset.bpend);
  });
  wireNeeds(panel, () => toggleBell(false));
}

function toggleBell(open){
  const panel = $("bellPanel"), bell = $("bBell");
  bellOpen = open === undefined ? !bellOpen : open;
  bell.setAttribute("aria-expanded", bellOpen ? "true" : "false");
  if (bellOpen){
    notesSeen = notes.length;          // opening it is reading it
    panel.hidden = false;
    drawBell();
    if (!noMotion())
      panel.animate([{opacity: 0, transform: "translateY(-10px)"},
                     {opacity: 1, transform: "none"}], {duration: 160, easing: "ease"});
  } else if (!panel.hidden){
    const hide = () => { panel.hidden = true; };
    if (noMotion()) hide();
    else {
      // oncancel as well as onfinish. Whether the panel is actually gone was
      // decided by an animation finishing, so an animation interrupted, by a
      // second toggle, by anything that animates this element: left bellOpen
      // false with the panel still on screen. drawBell then returned early on
      // the flag while the thing was in front of somebody, and it sat there
      // showing whatever it last drew.
      const out = panel.animate([{opacity: 1, transform: "none"},
                                 {opacity: 0, transform: "translateY(-10px)"}],
                                {duration: 120, easing: "ease"});
      out.onfinish = hide;
      out.oncancel = hide;
    }
  }
  drawBell();
}

// The presses on those rows, for whichever surface drew them: Dismiss and
// Show again change the rows where they are; a row's link leaves for the
// page it is about, and `after` runs as it does (the bell shuts itself).
function wireNeeds(root, after = () => {}){
  // Dismiss (bellseen.py): the update to that version, for this account, on
  // every browser it opens; a newer version notes again.
  root.querySelectorAll("[data-bdismiss]").forEach(a => a.onclick = async e => {
    e.preventDefault();
    const j = await (await postJSON("/api/bell", {action: "dismiss", keys: a.dataset.bdismiss.split(" ")}))
      .json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    refresh();
  });
  root.querySelectorAll("#bellRestore, [data-brestore]").forEach(restore => restore.onclick = async () => {
    const j = await (await postJSON("/api/bell", {action: "restore"})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    refresh();
  });
  root.querySelectorAll("[data-bci]").forEach(a => a.onclick = e => {
    e.preventDefault();
    after();
    sectOpen["git:ci"] = true;
    openNotebook(a.dataset.bci, "git");
  });
  // To the node the row is about, at the control it is about (Update agent
  // in its head bar): the press itself
  // stays there, beside the state line that says what it does.
  root.querySelectorAll("[data-bnode]").forEach(a => a.onclick = e => {
    e.preventDefault();
    after();
    openNodesTab(a.dataset.bnode, a.dataset.bwhat);
  });
  // ...and a toolchain update to that node's Toolchains tab.
  root.querySelectorAll("[data-btc]").forEach(a => a.onclick = e => {
    e.preventDefault();
    after();
    openToolchainsOn(a.dataset.btc);
  });
  // ...and a container update to the Docker tab on that node.
  root.querySelectorAll("[data-bdocker]").forEach(a => a.onclick = e => {
    e.preventDefault();
    after();
    if (a.dataset.bdocker) dockerNode = a.dataset.bdocker;
    openDocker();
  });
  // ...and an nginx update to the nginx tab on that node.
  root.querySelectorAll("[data-bnginx]").forEach(a => a.onclick = e => {
    e.preventDefault();
    after();
    openNginxTab(a.dataset.bnginx);
  });
}
