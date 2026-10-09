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

function logNote(msg, bad){
  // `bad` is kept beside `lv` because the row's own styling and every test
  // that reads it predate the third level; lv is what the dot is chosen from.
  notes.unshift({msg: String(msg), bad: level(bad) === "bad",
                 lv: level(bad), at: Date.now()});
  if (notes.length > NOTE_CAP) notes.length = NOTE_CAP;
  drawBell();
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
  const attOn = att.some(a => a.window) || ciRed.length ? "bad" : att.length ? "warn" : "";
  dot.hidden = !(pendingOn || att.length || ciRed.length || unread);
  // An ask outranks every level of record: one is a thing that happened, the
  // other is a thing that has not happened yet because it is waiting on you.
  // A node alert sits between: red when work is stopped, amber when an
  // update merely waits.
  dot.className = "dot" + (pendingOn ? " ask" : attOn ? " " + attOn : worst ? " " + worst : "");
  bell.classList.toggle("has", !!(pendingOn || att.length || ciRed.length || unread));
  bell.classList.toggle("waiting", pendingOn > 0);
  bell.title = pendingOn
    ? `${pendingOn} waiting on an answer`
    : att.length + ciRed.length ? `${att.length + ciRed.length} need${att.length + ciRed.length === 1 ? "s" : ""} attention`
    : unread ? `${unread} new` : "notifications";
  // Drawn whenever it is ON SCREEN, which is the question that matters, and
  // not when a flag says it is open; those two disagreed and the panel a
  // reader was looking at stopped updating.
  if (panel.hidden) return;
  const when = t => fmtTime(t, {hour: "2-digit", minute: "2-digit"});
  const rows = [
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
          : "needs your answer"}</div>
        <div class="bwhy">${esc(a.why)}</div>
        <div class="bcmd">${a.kind === "root" ? "# " : a.kind === "phone-use" ? "" : a.kind === "rebuild" || a.kind === "container" || a.kind === "sign" || a.kind === "sign-key" || a.kind === "release" || a.kind === "release-edit" || a.kind === "release-remove" ? "bb " : "adb "}${esc(a.cmd.join(" "))}</div>${
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
    // ...and the nodes. Out of window is red and names the projects it
    // stops; behind is amber and waits for a press on the Nodes tab.
    // A window move holds every project at once, so several of these is the
    // normal case after a minor bump and one row per project was six rows
    // saying one thing. Collapsed into one, with one press behind it (B93).
    ...att.map(a => a.kind === "toolchain"
      // A node with toolchains behind what is out, Claude Code among them
      // (toolchains.attention): one row per node in one shape for all of
      // them, amber, opening that node's Toolchains tab, where each is
      // updated (the operator, 9 Oct).
      ? `<div class="bnote ask">
        <div class="btag">toolchain update${a.tools.length === 1 ? "" : "s"} available</div>
        <div class="bwhy">on ${esc(a.node)}: ${a.tools.map(t =>
          // A check that cannot name the version out says "newer".
          `${esc(t.label)} ${esc(t.from || "?")} → ${t.to === "newer" ? "a newer version" : esc(t.to)}`).join(", ")}${
          a.tools.some(t => t.name === "claude-code") && a.projects.length
            ? `. Updating Claude Code ends the Claude sessions there first; ${a.projects.map(esc).join(", ")} run${
                a.projects.length === 1 ? "s" : ""} sessions there` : ""}</div>
        <div class="bfoot"><span>on the node's Toolchains tab</span>
          <span class="acts"><a href="#" data-btc="${esc(a.id)}">Toolchains tab</a></span></div></div>`
      : `<div class="bnote ask${a.window ? " bad" : ""}">
        <div class="btag">${a.window ? "agent out of window" : "agent update available"}</div>
        <div class="bwhy">${esc(a.node)} runs agent ${esc(a.from)} and this controller ships ${esc(a.to)}${
          a.window
            ? `.${a.projects.length
                ? ` ${a.projects.map(esc).join(", ")} cannot build, test or use the emulator there` : " Nothing works there"} until it is updated`
            : ""}</div>
        <div class="bfoot"><span>${a.window ? "work on it is stopped" : "on the Nodes tab"}</span>
          <span class="acts"><a href="#" data-bnode="${esc(a.id)}" data-bwhat="agent">Nodes tab</a></span></div></div>`),
    ...ciRed.map(c => `<div class="bnote ask bad">
        <div class="btag">CI failing in ${esc(projLabel(c.project))}</div>
        <div class="bwhy">${esc(c.text)}</div>
        <div class="bfoot"><span>this stays until the check passes again</span>
          <span class="acts">${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">On GitHub</a>` : ""}
            <a href="#" data-bci="${esc(c.project)}">Git view</a></span></div></div>`),
    ...notes.map(n => `<div class="bnote${n.lv === "info" ? "" : " " + n.lv}">
        <div class="bwhy">${esc(n.msg)}</div>
        <div class="bfoot"><span>${when(n.at)}</span></div></div>`),
  ];
  panel.innerHTML = rows.length
    ? rows.join("") + (notes.length
        ? `<div class="bfootbar"><button type="button" id="bellClear">Clear</button></div>` : "")
    : `<div class="bempty">nothing to report</div>`;
  // Any press in the drawer closes it, after the press's own handler has
  // run (the operator, 7 Oct): Approve, Deny, an invitation's answer, Clear,
  // a link to where a row is about. One listener on the drawer, so a row
  // added later is covered without remembering to.
  panel.onclick = e => {
    if (e.target.closest?.("button, a")) queueMicrotask(() => toggleBell(false));
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
  panel.querySelectorAll("[data-bci]").forEach(a => a.onclick = e => {
    e.preventDefault();
    toggleBell(false);
    sectOpen["git:ci"] = true;
    openNotebook(a.dataset.bci, "git");
  });
  // To the node the row is about, at the control it is about (Update agent
  // in its head bar): the press itself
  // stays there, beside the state line that says what it does.
  panel.querySelectorAll("[data-bnode]").forEach(a => a.onclick = e => {
    e.preventDefault();
    toggleBell(false);
    openNodesTab(a.dataset.bnode, a.dataset.bwhat);
  });
  // ...and a toolchain update to that node's Toolchains tab.
  panel.querySelectorAll("[data-btc]").forEach(a => a.onclick = e => {
    e.preventDefault();
    toggleBell(false);
    openToolchainsOn(a.dataset.btc);
  });
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
