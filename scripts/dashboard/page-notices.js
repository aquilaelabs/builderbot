// The Notifications page (R218 step 6, the design's the-dashboard/notifications
// rule), at #/notifications, opened from the bell's See all. Two parts:
//
//   Waiting on you: every ask, invitation and held change, each a row with
//   what it is and what it would run, its Approve and Deny ON the row, and
//   the long part (a compose file, the lines a push flagged, a release's
//   notes) whole in a scrolling box behind a fold.
//
//   History: what the page has said to this account, kept on the server
//   (notices.py) across reloads and browsers, newest first, narrowed by
//   chips (what was said, answers to asks, jobs, failures), each row with
//   its own delete, and Clear for the lot or the chip in force.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

let noticesData = null;          // the account's notices, or null before the first read
let noticesRev = 0;
let noticesErr = "";
let noticesChip = "";            // the chip in force: "", a kind, or "bad" for failures
let noticesFetching = false;

function openNotices(){
  openTab({kind: "notices", arg: "__notices", label: "Notifications"});
}

async function loadNotices(){
  if (noticesFetching) return;
  noticesFetching = true;
  try{
    const j = await (await fetch("/api/notices")).json();
    noticesErr = j.error || "";
    noticesData = j.notices || [];
  }catch(e){
    noticesErr = "could not read the notices: " + e;
    noticesData = noticesData || [];
  }finally{
    noticesFetching = false;
  }
  noticesRev++;
  drawPanes();
}

async function noticesAct(body){
  const j = await (await postJSON("/api/notices", body)).json().catch(() => ({error: "no answer"}));
  if (j.error) notify(j.error, true);
  await loadNotices();
}

const NOTICE_KINDS = {said: "Said", ask: "Answers", job: "Jobs"};

// Every ask, as a row: what it is and what it would run, its answer on the
// row, and the long part in a scrolling box behind a fold.
function noticesAskRows(){
  const asks = ph?.asks || [];
  const long = a => a.kind === "push" ? ["the flagged lines, which approving okays until they change", a.detail]
    : a.kind === "container" ? ["the compose file" + (a.env_keys?.length ? `, and an env file setting ${a.env_keys.join(", ")}` : ""), a.detail]
    : a.kind === "release-edit" ? ["the new notes", a.detail] : ["", ""];
  return asks.map(a => {
    const [what, body] = long(a);
    return `<div class="row stack2 ntask${a.kind === "root" || a.kind === "release-remove" ? " bad" : ""}" data-ask="${a.id}">
      <div class="grow">
        <div class="name">${askTag(a)}</div>
        <div class="sub">${esc(a.why || "")}</div>
        <div class="bcmd">${askCmd(a)}</div>
        ${body ? `<details class="ntlong"${sectAttr("notices:ask:" + a.id)}><summary>${esc(what)}</summary><pre class="ntbox">${esc(body)}</pre></details>` : ""}
        <div class="sub dim">${a.asker ? esc(a.asker) + "'s session · " : ""}${askLeft(a)}</div>
      </div>
      <div class="actbar">${askActs(a, {deny: "data-ntdeny", allow: "data-ntallow"})}</div>
    </div>`;
  });
}

function noticesWaitingRows(){
  const invites = (state?.invites || []).map(i => `<div class="row stack2" data-invite="${i.id}">
      <div class="grow"><div class="name">${i.kind === "owner" ? `${esc(projLabel(i.project))} offered to you` : `Invited to ${esc(projLabel(i.project))}`}</div>
        <div class="sub">${esc(i.by || "Somebody")} ${i.kind === "owner" ? "offers you ownership" : `invited you${i.role ? ` as ${esc(i.role)}` : ""}`} · ${esc(ago(i.at))}</div></div>
      <div class="actbar"><button type="button" data-ntinvite="${i.id}" data-yes="0">Decline</button>
        <button type="button" class="primary" data-ntinvite="${i.id}" data-yes="1">Accept</button></div></div>`);
  const held = (state?.projects || []).filter(p => p.pending > 0).map(p => `<div class="row stack2">
      <div class="grow"><div class="name">${p.pending} change${p.pending === 1 ? "" : "s"} from a session in ${esc(projLabel(p.name))}</div>
        <div class="sub">waiting for your approval on its notebook</div></div>
      <div class="actbar"><button type="button" data-ntpend="${esc(p.name)}">Review</button></div></div>`);
  return [...noticesAskRows(), ...invites, ...held];
}

function noticesShown(){
  const all = noticesData || [];
  return noticesChip === "bad" ? all.filter(n => n.level === "bad")
    : noticesChip ? all.filter(n => n.kind === noticesChip) : all;
}

function renderNoticesInto(i){
  const d = docSurface(i, "notices");
  if (!d) return;
  if (noticesData === null){
    // Its template (R218 step 16): the History section and its name are the
    // page's own; what was kept is on its way.
    d.setBar(`<span class="dim">${skv(4)}</span>`);
    d.list.innerHTML = skTpl(docSection("notices", "history", "History", "", skRows(5)));
    if (!noticesFetching) loadNotices();
    return;
  }
  const all = noticesData, rows = noticesShown(), waiting = noticesWaitingRows();
  const groups = [...Object.entries(NOTICE_KINDS).map(([k, label]) => ({key: k, label, count: all.filter(n => n.kind === k).length})),
                  {key: "bad", label: "Failures", count: all.filter(n => n.level === "bad").length}];
  d.setBar(`<span class="dim">${all.length} kept</span><span class="sp"></span>
    ${all.length ? `<button type="button" class="danger" id="ntClear">${noticesChip && noticesChip !== "bad" ? `Clear ${esc(NOTICE_KINDS[noticesChip].toLowerCase())}` : "Clear all"}</button>` : ""}`);
  const html = (noticesErr ? `<div class="hint bad">${esc(noticesErr)}</div>` : "")
    // Not drawn with nothing in it (the house rule: what has nothing to act
    // on is not shown); while something waits it opens by itself, and on a
    // phone, one section at a time, it is the one.
    + (waiting.length ? docSection("notices", "waiting", "Waiting on you", String(waiting.length), waiting.join(""),
                                   {loud: true, prime: true}) : "")
    + docSection("notices", "history", "History", String(rows.length),
                 chipBar(groups, noticesChip, "data-ntchip")
                 + (rows.length ? `<div class="ntlist">${rows.map(n => `<div class="row ntrow ${esc(n.level)}" data-nt="${esc(n.id)}">
                       <span class="tic">${TOAST_ICONS[n.level] || TOAST_ICONS.info}</span>
                       <span class="grow"><span class="nttext">${esc(n.text)}</span>
                         <span class="sub dim">${esc(NOTICE_KINDS[n.kind] || n.kind)} · ${esc(ago(n.at))}</span></span>
                       ${n.job ? `<button type="button" data-ntjob="${esc(n.job)}">Job</button>` : ""}
                       <button type="button" class="ic" data-ntdel="${esc(n.id)}" aria-label="delete this notice">×</button>
                     </div>`).join("")}</div>`
                   : `<div class="hint">${all.length ? "none of this kind" : "nothing yet: what the page tells you is kept here"}</div>`),
                 {prime: !waiting.length});
  if (!paint(d.list, html)) return;
  const list = d.list.querySelector(".ntlist");
  if (list) paginate(list, ":scope > .ntrow", {key: "ntList", noun: "notices"});
  wireNotices(d.el);
}

function wireNotices(root){
  wireSections(root);
  const clear = root.querySelector("#ntClear");
  if (clear) clear.onclick = () => {
    const kind = noticesChip && noticesChip !== "bad" ? noticesChip : "";
    if (!confirm(kind ? `Clear every ${NOTICE_KINDS[kind].toLowerCase()} notice?` : "Clear every notice kept for your account?")) return;
    noticesAct({action: "clear", kind});
  };
  root.querySelectorAll("[data-ntchip]").forEach(b => b.onclick = () =>
    fadeThrough(".pane .doc.on .ntlist", () => { noticesChip = b.dataset.ntchip; noticesRev++; drawPanes(); }));
  root.querySelectorAll("[data-ntdel]").forEach(b => b.onclick = () => noticesAct({action: "delete", id: b.dataset.ntdel}));
  root.querySelectorAll("[data-ntjob]").forEach(b => b.onclick = () => openJob(b.dataset.ntjob));
  root.querySelectorAll("[data-ntallow]").forEach(b => b.onclick = () => askAnswer(Number(b.dataset.ntallow), true, !!b.dataset.session));
  root.querySelectorAll("[data-ntdeny]").forEach(b => b.onclick = () => askAnswer(Number(b.dataset.ntdeny), false));
  root.querySelectorAll("[data-ntinvite]").forEach(b => b.onclick = async () => {
    const yes = b.dataset.yes === "1";
    const j = await (await postJSON("/api/members", {action: yes ? "accept" : "decline", id: Number(b.dataset.ntinvite)})).json().catch(() => ({}));
    notify(j.error || (yes ? `you are on ${projLabel(j.project)} now` : `declined ${projLabel(j.project)}`), !!j.error, {kind: "ask"});
    refresh();
  });
  root.querySelectorAll("[data-ntpend]").forEach(b => b.onclick = () => { openNotebook(b.dataset.ntpend); openPending(b.dataset.ntpend); });
}
