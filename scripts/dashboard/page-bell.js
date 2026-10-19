// What the page has said: a toast for the moment, and the bell, which
// keeps the last fifty and what waits on this account (a session's ask, a
// held change).
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- toasts -------------------------------------------------------------
// One stack at a corner (R218 step 6, the design's the-dashboard/notifications
// rule): the bottom left above the dock's line, beside a dialog when one is
// open (toastPlace), the newest at the foot, at most TOAST_MAX on screen, each with its
// kind's icon and its own ×, gone after a while but held while the pointer
// is over the stack, so a sentence being read does not leave mid-read. And
// every one is on the record: the bell's latest for this page, and the
// account's notices (notices.py), read on the Notifications page.

// How bad is it: "info", "warn" or "bad". The second argument was a boolean
// and sixty-odd callers pass `true` for a failure, so `true` still means what
// it always did and "warn" is the new middle: a caller that never learns
// about it keeps working and keeps meaning the same thing.
function level(v){
  return v === true || v === "bad" ? "bad" : v === "warn" ? "warn" : "info";
}

const TOAST_MAX = 4;
// The kind's mark: a dot of information, a warning's bang, a failure's cross.
const TOAST_ICONS = {
  info: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2"/><path d="M8 7.2v4"/><path d="M8 4.9h.01"/></svg>`,
  warn: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.4 14.2 13H1.8z"/><path d="M8 6.6v3.2"/><path d="M8 11.5h.01"/></svg>`,
  bad: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2"/><path d="m5.8 5.8 4.4 4.4M10.2 5.8l-4.4 4.4"/></svg>`,
};
let toastHeld = false;

// `opts.kind` is what the record files it under ("said", the default, or
// "ask" or "job"); `opts.job` names the job it is about.
function notify(msg, bad, opts = {}){
  const lv = level(bad);
  toastAdd(String(msg), lv);
  logNote(msg, bad);
  keepNotice({text: String(msg), level: lv, kind: opts.kind || "said", job: opts.job || ""});
}

function toastAdd(text, lv){
  const stack = $("toast");
  if (!stack) return null;
  const el = document.createElement("div");
  el.className = "tst " + lv;
  el.innerHTML = `<span class="tic">${TOAST_ICONS[lv] || TOAST_ICONS.info}</span><span class="tmsg"></span>
    <button type="button" class="ic tx" aria-label="dismiss">×</button>`;
  el.querySelector(".tmsg").textContent = text;
  el.querySelector(".tx").onclick = () => toastGone(el);
  stack.append(el);
  // The oldest goes first, but not a running job's, which is followed.
  while (stack.children.length > TOAST_MAX)
    ([...stack.children].find(c => !c.classList.contains("job")) || stack.firstElementChild).remove();
  if (!noMotion()) el.animate([{opacity: 0, transform: "translateY(8px)"}, {opacity: 1, transform: "none"}],
                              {duration: 160, easing: "ease"});
  el.left = lv === "info" ? 4000 : 7000;
  toastTick(el);
  toastPlace(stack);
  return el;
}

// Where the stack goes while a dialog is open. No corner of the page is
// free of controls (a dialog's buttons sit at the left of its foot on some
// and the right on others), and a refusal is most often said while one is
// open, so the stack leaves the dialog's box: into the wider gutter beside
// it at a desk, and where neither is wide enough (a phone, a narrow window)
// to the top of the screen, letting every press through and going by its
// clock, since what it said is on the record either way. With no dialog
// open the stylesheet's corner holds.
const TOAST_GUTTER = 240;
function toastPlace(stack){
  const box = [...document.querySelectorAll(".modal:not([hidden]):not(.inline):not(.leaving) > .box")].at(-1);
  stack.style.cssText = "";
  stack.classList.toggle("overdlg", false);
  if (!box) return;
  const r = box.getBoundingClientRect(), rail = $("rail")?.getBoundingClientRect().right || 0;
  const right = innerWidth - r.right - 24, left = r.left - rail - 24;
  if (Math.max(right, left) >= TOAST_GUTTER){
    const w = Math.min(420, Math.max(right, left));
    stack.style.cssText = right >= left ? `left:auto;right:12px;width:${w}px` : `right:auto;left:${rail + 12}px;width:${w}px`;
    return;
  }
  stack.classList.add("overdlg");
}

// Each toast's own clock, which stops while the stack is held and goes on
// with what it had left when the pointer leaves.
function toastTick(el){
  clearTimeout(el.timer);
  if (toastHeld || el.left === Infinity) return;
  el.started = Date.now();
  el.timer = setTimeout(() => toastGone(el), el.left);
}
function toastHold(on){
  toastHeld = on;
  for (const el of $("toast")?.children || []){
    if (on){ clearTimeout(el.timer); if (el.started) el.left = Math.max(1500, el.left - (Date.now() - el.started)); }
    else toastTick(el);
  }
}
function toastGone(el){
  clearTimeout(el.timer);
  if (!el.isConnected) return;
  if (noMotion()){ el.remove(); return; }
  const out = el.animate([{opacity: 1}, {opacity: 0}], {duration: 140, easing: "ease"});
  out.onfinish = out.oncancel = () => el.remove();
}

// A job's toast (R218 step 6): it stays while the job runs, its line the
// job's state and step as the queue reports them, read again each time the
// jobs token moves; when the job ends it takes the outcome's tone, starts
// its clock like any other, and the outcome is kept on the record as a
// job's (kind "job", with the job's id, which the Notifications page opens).
// Dismissed before then, it is still followed, so the end is still kept.
const jobToasts = new Map();     // job id -> {el, label}
// onEnd(job), when given, is called once the job is over: what pressed it
// frees itself then, rather than waiting out a window of its own (B862).
function notifyJob(id, label, onEnd){
  if (!id) return notify(label);
  const el = toastAdd(`${label}: queued`, "info");
  if (el){ el.classList.add("job"); el.left = Infinity; clearTimeout(el.timer); }
  jobToasts.set(id, {el, label, onEnd});
  logNote(`${label}: queued`, false);
  jobToastsCheck();
}
async function jobToastsCheck(){
  for (const [id, t] of [...jobToasts]){
    let j;
    try{ j = await (await fetch(`/api/v1/jobs?id=${encodeURIComponent(id)}`)).json(); }catch(e){ continue; }
    // A job carries an error field of its own (a failed one's reason), so
    // the read is good when it names the job.
    if (!j || j.id !== id){ jobToasts.delete(id); continue; }
    const over = ["succeeded", "failed", "canceled"].includes(j.state);
    const line = over ? `${t.label}: ${j.state}${j.state === "failed" && j.error ? " (" + j.error + ")" : ""}`
      : `${t.label}: ${j.state === "running" && j.step ? j.step : j.state}`;
    if (t.el?.isConnected) t.el.querySelector(".tmsg").textContent = line;
    if (!over) continue;
    jobToasts.delete(id);
    try{ t.onEnd?.(j); }catch(e){ console.error(e); }
    const lv = j.state === "failed" ? "bad" : j.state === "canceled" ? "warn" : "info";
    if (t.el?.isConnected){
      t.el.className = "tst " + lv;
      t.el.querySelector(".tic").innerHTML = TOAST_ICONS[lv];
      t.el.left = lv === "info" ? 4000 : 7000;
      toastTick(t.el);
    }
    logNote(line, lv === "info" ? false : lv);
    keepNotice({text: line, level: lv, kind: "job", job: id});
  }
}

// Onto the account's record, a few at a time: a burst of toasts is one
// write. Never a toast of its own when it fails, which would be a loop.
let noticeQueue = [], noticeTimer = null;
function keepNotice(n){
  if (!state?.uid) return;
  noticeQueue.push(n);
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(async () => {
    const items = noticeQueue.splice(0);
    try{ await postJSON("/api/notices", {action: "add", items}); }catch(e){ /* the toast was said */ }
    if (shown("notices")) loadNotices();
  }, 400);
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
      <div class="bfoot"><span>on its Toolchains page</span>
        <span class="acts">${keys ? `<a href="#" data-bdismiss="${esc(keys)}">Dismiss</a>` : ""}
          <a href="#" data-btc="${esc(a.id)}">Toolchains page</a></span></div></div>`;
  }
  // A session the controller's outage held (R251): it was told to write
  // where it was and stop; Resume tells it to pick up from that note.
  if (a.kind === "held"){
    return `<div class="bnote att warn">
      <div class="bt">A session in ${esc(projLabel(a.project))} stopped for the update</div>
      <div class="bsum">${esc(a.who ? `${a.who}'s` : "A")} Claude session on ${esc(a.node)}, held ${a.since ? esc(ago(a.since)) : "while BuilderBot was away"}</div>
      <div class="bfoot"><span>it left a note of where it was</span>
        <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
          <a href="#" data-bheld="${esc(a.node_id)}" data-session="${esc(a.session)}" data-claude="${esc(a.claude || a.session)}">Resume</a></span></div></div>`;
  }
  // A copy or move that did not happen: the reason, which used to sit on
  // the container's row for ever, here where it can be put away.
  if (a.kind === "relocate"){
    return `<div class="bnote att bad">
      <div class="bt">Copying or moving ${esc(a.name)} did not happen</div>
      <div class="bsum">${esc(a.why)}</div>
      <div class="bfoot"><span>${a.at ? esc(ago(a.at)) : "on the Containers page"}</span>
        <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
          <a href="#" data-bdocker="${esc(a.node_id)}">Containers page</a></span></div></div>`;
  }
  // A container whose registry image moved (R195): one note per node, to
  // the Docker tab on that node, where Update is on each row.
  if (a.kind === "image"){
    const n = a.containers.length;
    return `<div class="bnote att">
      <div class="bt">${n} container update${n === 1 ? "" : "s"} on ${esc(a.node)}</div>
      <div class="bsum">${a.containers.map(c => `${esc(c.name)} (${c.images.map(esc).join(", ")})`).join(", ")}</div>
      <div class="bfoot"><span>on its Containers page</span>
        <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
          <a href="#" data-bdocker="${esc(a.id)}">Containers page</a></span></div></div>`;
  }
  // A node's nginx behind the newest line (R192): its own note, to the
  // nginx tab on that node, where Update is.
  if (a.kind === "nginx"){
    return `<div class="bnote att">
      <div class="bt">nginx update on ${esc(a.node)}</div>
      <div class="bsum">${a.rebuild ? `runs ${esc(a.from)}; a newer build of that tag is out`
        : `runs ${esc(a.from)} and ${esc(a.to)} is out`}</div>
      <div class="bfoot"><span>on its nginx page</span>
        <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
          <a href="#" data-bnginx="${esc(a.id)}">nginx page</a></span></div></div>`;
  }
  return `<div class="bnote att${a.window ? " bad" : ""}">
    <div class="bt">${a.window ? `${esc(a.node)}'s agent is out of window` : `Agent update on ${esc(a.node)}`}</div>
    <div class="bsum">runs agent ${esc(a.from)} and this controller ships ${esc(a.to)}${a.window
      ? `: ${a.projects.length ? `${a.projects.length} project${a.projects.length === 1 ? "" : "s"} cannot build, test or use the emulator there`
                               : "nothing works there"} until it is updated` : ""}</div>
    ${a.window && a.projects.length ? `<details class="bdetail"${sectAttr("bell:agent:" + a.id)}><summary>projects</summary><pre>${
      a.projects.map(esc).join(", ")}</pre></details>` : ""}
    ${a.failed ? `<div class="bsum bad">its last update failed: ${esc(a.failed)}</div>` : ""}
    <div class="bfoot"><span>${a.window ? "work on it is stopped"
      : a.auto ? (a.failed ? "tried again once the node is idle, or press Update agent there" : "updates itself once the node is idle")
      : "on the Nodes page"}</span>
      <span class="acts">${a.key ? `<a href="#" data-bdismiss="${esc(a.key)}">Dismiss</a>` : ""}
        <a href="#" data-bnode="${esc(a.id)}" data-bwhat="agent">Nodes page</a></span></div></div>`;
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

// What an ask is, in one line: the machine and that it is root there, the
// project and the verb, a container and its node. The bell's row and the
// Notifications page's both lead with it.
function askTag(a){
  return (
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
          : "needs your answer");
}

// The command an ask would run, with the prompt it runs at: root's #, bb's
// verbs, adb's for a phone.
function askCmd(a){
  const pre = a.kind === "root" ? "# " : a.kind === "phone-use" ? ""
    : ["rebuild", "container", "sign", "sign-key", "release", "release-edit", "release-remove", "push"].includes(a.kind) ? "bb " : "adb ";
  return pre + esc((a.cmd || []).join(" "));
}

// How long an ask has left to be answered, said the same everywhere it is
// shown (consistency batch J: five copies of the sum).
function askLeft(a){
  return a.left > 60 ? `${Math.floor(a.left / 60)} min left to answer` : `${a.left}s left to answer`;
}
// Whose session asks, the project by its label.
function askWho(a){
  return a.asker ? `${a.asker}'s session in ${a.project ? projLabel(a.project) : "a project"}` : a.project ? projLabel(a.project) : "a session";
}
// The answers to an ask, in one order and one word on every page: Deny,
// then, for a phone's commands that come one after another, Approve for
// this session, then Approve as the primary, last, as an inline ask's verb
// is. Pages said Allow or Approve, put Approve first or last, and one drew
// Deny as destructive. `deny`, `allow` and `session` are the page's own
// data keys, which its wiring reads.
function askActs(a, {deny, allow, session = "data-session"}){
  const many = a.kind === "phone" || a.kind === "phone-use";
  return `<button type="button" ${deny}="${a.id}">Deny</button>${many ? `
    <button type="button" ${allow}="${a.id}" ${session}="1"
      title="this one, and the rest this session sends to the phone, without asking">Approve for this session</button>` : ""}
    <button type="button" class="primary" ${allow}="${a.id}">Approve</button>`;
}

// An answer to an ask, from the bell or the Notifications page, and onto
// the account's record (kind "ask"): which ask, and what was said to it.
function askAnswer(id, allow, session = false){
  const a = (ph?.asks || []).find(x => x.id === id);
  if (allow){ phBusy = "running it"; phRev++; drawPanes(); }
  phFetch(allow ? {action: "allow", id, session} : {action: "deny", id});
  if (a){
    const plain = document.createElement("i");
    plain.innerHTML = askTag(a).replace(/: needs your answer$/, "");
    keepNotice({text: `${allow ? (session ? "Approved for the session" : "Approved") : "Denied"}: ${plain.textContent}${
      (a.cmd || []).length ? ` (${a.cmd.join(" ")})` : ""}`, level: allow ? "info" : "warn", kind: "ask"});
  }
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
  // Claude sessions sitting on Claude Code's own permission prompt (B52),
  // which only their terminal can answer: the row opens it.
  const asking = (state?.sessions || []).filter(s => s.claude?.state === "asking");
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
  const pendingOn = asks.length + waiting.length + invites.length + asking.length;
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
  setHidden(dot, !(pendingOn || att.length || ciRed.length || syncC.length || unread));
  // An ask outranks every level of record: one is a thing that happened, the
  // other is a thing that has not happened yet because it is waiting on you.
  // A node alert sits between: red when work is stopped, amber when an
  // update merely waits.
  setClass(dot, "dot" + (pendingOn ? " ask" : attOn ? " " + attOn : worst ? " " + worst : ""));
  bell.classList.toggle("has", !!(pendingOn || att.length || ciRed.length || syncC.length || unread));
  bell.classList.toggle("waiting", pendingOn > 0);
  // Its description directly, and only when it changed: a title written on
  // every draw was taken off again by untitle() each time (R218 step 10).
  setAttr(bell, "aria-description", pendingOn
    ? `${pendingOn} waiting on an answer`
    : att.length + ciRed.length + syncC.length
      ? `${att.length + ciRed.length + syncC.length} need${att.length + ciRed.length + syncC.length === 1 ? "s" : ""} attention`
    : unread ? `${unread} new` : "notifications");
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
        <div class="btag">${askTag(a)}</div>
        <div class="bwhy">${esc(a.why)}</div>
        <div class="bcmd">${askCmd(a)}</div>${
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
        <div class="bfoot"><span>${a.asker ? esc(a.asker) + "'s session · " : ""}${askLeft(a)}</span>
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
    ...asking.map(s => `<div class="bnote ask">
        <div class="btag">asking you in its terminal</div>
        <div class="bwhy">Claude on ${esc(projLabel(s.name.replace(/^claude-/, "")))}: ${esc(s.claude.task || "waiting for you to answer it")}</div>
        <div class="bfoot"><span>on ${esc(s.node || "this machine")}</span>
          <span class="acts"><a href="#" data-bask="${esc(s.name)}">Open it</a></span></div></div>`),
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
  const group = (title, list, extra = "", total = list.length) => list.length
    ? `<div class="bgroup"><span>${title} · ${total}</span>${extra}</div>` + list.join("") : "";
  const putAway = hidden ? `<div class="bfootbar"><span>${hidden} update${hidden === 1 ? "" : "s"} dismissed</span>
      <button type="button" id="bellRestore">Show again</button></div>` : "";
  // A short list (R218 step 6): what waits on an answer, what needs doing,
  // then the latest five of what the page said, and See all for the rest
  // and the account's whole record on the Notifications page.
  const seeAll = `<div class="bfootbar"><button type="button" id="bellAll">See all</button></div>`;
  panel.innerHTML = (answer.length + needs.length + said.length
    ? group("Waiting on you", answer) + group("Needs attention", needs)
      + group("Recent", said.slice(0, 5), `<button type="button" id="bellClear">Clear</button>`, said.length)
    : `<div class="bempty">nothing to report</div>`) + putAway + seeAll;
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
  const all = $("bellAll");
  if (all) all.onclick = () => { toggleBell(false); openNotices(); };
  const clear = $("bellClear");
  // Only the page's own log clears: an ask is not this button's to dismiss.
  if (clear) clear.onclick = () => { notes = []; notesSeen = 0; drawBell(); };
  panel.querySelectorAll("[data-ballow]").forEach(a => a.onclick = e => {
    e.preventDefault();
    askAnswer(Number(a.dataset.ballow), true, !!a.dataset.bsession);
  });
  panel.querySelectorAll("[data-bdeny]").forEach(a => a.onclick = e => {
    e.preventDefault();
    askAnswer(Number(a.dataset.bdeny), false);
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
  panel.querySelectorAll("[data-bask]").forEach(a => a.onclick = e => {
    e.preventDefault();
    toggleBell(false);
    openTab({kind: "term", arg: argForSession(a.dataset.bask), label: a.dataset.bask});
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
    // ...and it hides only a panel still meant to be shut: pressed open again
    // inside the 120ms, the old close's end hid it (B855, as the gear's did).
    const hide = () => { if (!bellOpen) panel.hidden = true; };
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
  // Resume (R251): the session an outage held is told to pick up from its
  // note; the row goes once the line was sent. One send at a time: a second
  // press while the first is out typed the line twice (B775).
  root.querySelectorAll("[data-bheld]").forEach(a => a.onclick = async e => {
    e.preventDefault();
    if (a.getAttribute("aria-busy") === "true") return;
    a.setAttribute("aria-busy", "true");
    const j = await (await postJSON("/api/bell", {action: "resume", node: a.dataset.bheld, session: a.dataset.session}))
      .json().catch(() => ({error: "no answer"}));
    a.removeAttribute("aria-busy");
    notify(j.error || (j.sent ? `told ${a.dataset.claude} to pick up where it stopped`
                                : `the line is in ${a.dataset.claude}'s input, not sent: it was busy (a turn or its check running) or a question was on its screen; Enter in it sends it`), !!j.error);
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
