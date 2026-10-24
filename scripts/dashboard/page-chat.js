// Chat: the messages between people and sessions on a project, read and
// sent from the dock's Chat tab.
// One classic script beside index.html (docs/design-language.md, Files): pure
// declarations, nothing runs at load.

"use strict";

let chatWith = null;                 // {who} or {project}, or null for the list
let chatMsgs = [], chatDraft = {}, chatSeenRev = -1;
let chatDrawn = "";                  // what the open conversation was last painted from

const chatKey = w => w?.project ? `p:${w.project}` : w?.who ? `dm:${w.who}` : "";

async function loadChat(){
  if (!chatWith){ drawChat(); return; }
  try{
    const r = await (await fetch("/api/chat", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "read", ...chatWith }) })).json();
    if (r.error){ notify(r.error, true); chatWith = null; }
    else { chatMsgs = r.messages || []; chatSeenRev = r.rev; }
  }catch(e){ /* the poll will come back to it */ }
  drawChat();
  refreshSoon();                     // the unread counts move with it
}

// An open chat follows the chat's revision, which every message moves (R218
// step 10, page-poll.js's watch on "chat").
function chatOpen(w){ chatWith = w; chatMsgs = []; chatDrawn = ""; loadChat(); }

// The chat is the dock's Chat tab (R250 step 2): a tab of its own kind that
// lives in the dock as a terminal does, its body the list of people and
// project channels beside the open conversation at a desk, one at a time
// on a phone, the composer at the foot. Chat on the dock's line opens it,
// and pressed again while it is in front puts the dock down.
function openChatTab(){
  const t = tabs.find(x => x.kind === "chat");
  if (t && panes[1] === t.id && dockUp){ dockShow(t.id); return; }
  if (t){ dockShow(t.id); return; }
  openTab({kind: "chat", arg: "__chat", label: "Chat"});
}

function renderChatInto(i){
  const el = $("doc" + i);
  if (!el) return;
  if (!el.classList.contains("flush")) el.classList.add("flush");
  if (!el.querySelector(":scope > .chattab")){
    el.innerHTML = `<div class="chattab"><div class="chatlist"></div><div class="chatthread" id="chat"></div></div>`;
    chatDrawn = "";
  }
  drawChat();
}

function drawChat(){
  const box = document.querySelector(".chattab");
  if (!box) return;
  setClass(box, "chattab" + (chatWith ? " open" : ""));
  drawChatList(box.querySelector(".chatlist"));
  drawChatThread(box.querySelector(".chatthread"));
}

// The people and the project channels, each with its unread count.
function drawChatList(el){
  const c = state?.chat;
  if (!c || !c.people) return paint(el, `<div class="hint">sign in to chat</div>`);
  const unread = c.unread || {};
  const cur = chatKey(chatWith);
  const here = new Set(c.online || []);
  // When each was last here, beside the name (the operator, 4 Oct): "here
  // now" for whoever is, the time since for everybody else.
  const seenAt = c.seen || {};
  const lastSeen = n => here.has(n) ? "here now" : seenAt[n] ? ago(seenAt[n]) : "never signed in";
  const people = (c.people || []).map(n =>
    `<button type="button" class="row chatrow${cur === "dm:" + n ? " on" : ""}" data-who="${esc(n)}">
       <span class="dot ${here.has(n) ? "ok" : ""}"></span>
       <span class="grow">${esc(n)} <span class="dim chatseen">(${esc(lastSeen(n))})</span></span>
       ${unread["dm:" + n] ? `<span class="pill">${unread["dm:" + n]}</span>` : ""}
     </button>`);
  // A project channel is the group chat for everybody on it, and it is where
  // the Claude sessions and the prompts land. An ADMIN is shown every one;
  // they are shown every project (roadmap #27) and the same rule decides
  // this, with the ones they have actually taken on marked and sorted
  // first, so "mine" and "everything else on the box" are one glance apart
  // rather than one read of a list of forty.
  const ps = [...(state?.projects || [])]
    .sort((a, b) => (notMine(a) - notMine(b)) || byProjectName(a, b));
  const projs = ps.map(p => {
    // Unread is only ever marked on a channel that is YOURS. An admin is
    // shown every project's channel and most are somebody else's business:
    // coloring those would be a page permanently asking to be read.
    const n = notMine(p) ? 0 : unread["p:" + p.name] || 0;
    return `<button type="button" class="row chatrow${notMine(p) ? " notmine" : ""}${
      n ? " unread" : ""}${cur === "p:" + p.name ? " on" : ""}" data-proj="${esc(p.name)}"
       ${notMine(p) ? `title="you have not taken this project on; you can read it"` : ""}>
       <span class="grow">#${esc(projLabel(p.name))}</span>
       ${n ? `<span class="pill">${n}</span>` : ""}
     </button>`;
  });
  const mine = ps.filter(p => !notMine(p)).length;
  if (!paint(el, `<div class="sub chathead">people</div>`
      + (people.length ? people.join("") : `<div class="hint">no other accounts</div>`)
      + (projs.length ? `<div class="sub chathead">projects${
           mine < ps.length ? `, yours first` : ""}</div>` + projs.join("") : ""))) return;
  el.querySelectorAll("[data-who]").forEach(b =>
    b.onclick = e => { e.stopPropagation(); chatOpen({ who: b.dataset.who }); });
  el.querySelectorAll("[data-proj]").forEach(b =>
    b.onclick = e => { e.stopPropagation(); chatOpen({ project: b.dataset.proj }); });
}

// The open conversation: its head, the log and the composer at the foot.
function drawChatThread(el){
  const c = state?.chat;
  if (!c || !c.people){ chatDrawn = ""; return paint(el, ""); }
  if (!chatWith){
    chatDrawn = "";
    return paint(el, `<div class="hint chatpick">a person or a project's channel, from the list</div>`);
  }
  // A person's name carries when they were last here, as it does in the list.
  const lastIn = n => new Set(c.online || []).has(n) ? "here now"
    : c.seen?.[n] ? ago(c.seen[n]) : "never signed in";
  const title = chatWith.project ? "#" + projLabel(chatWith.project) : `${chatWith.who} (${lastIn(chatWith.who)})`;
  const key = chatKey(chatWith);
  // Painted only when the conversation changed: the poll repainted the
  // panel whole and pinned the log to its end, and a reader scrolled up to
  // an older message was dragged back down each time (the operator, 25
  // Sep). And when it is painted, the reader keeps their place unless they
  // were at the end, where the newest message is what they want. The minute
  // is in it so "3 min ago" still moves, once a minute.
  const sig = key + "\n" + Math.floor(Date.now() / 60000) + "\n"
    + chatMsgs.map(m => `${m.at}\t${m.who}\t${m.kind}\t${m.text}`).join("\n");
  if (sig === chatDrawn && el.querySelector("#chatlog")) return;
  chatDrawn = sig;
  const was = el.querySelector("#chatlog");
  const atEnd = !was || was.scrollTop + was.clientHeight >= was.scrollHeight - 8;
  const keep = was ? was.scrollTop : 0;
  paint(el, `
    <div class="chathead">
      <button type="button" class="link" id="chatBack">‹ all</button>
      <b class="grow">${esc(title)}</b>
    </div>
    ${chatWith.project ? `<div class="sub chatnote">everyone on this project sees this</div>` : ""}
    <div class="chatlog" id="chatlog">${chatMsgs.map(m => `
      <div class="chatmsg${m.kind === "did" || m.kind === "asked" ? " ev" : ""}">
        <span class="dim">${esc(m.who || "?")} · ${ago(m.at)}</span>
        <div>${esc(m.text)}</div>
      </div>`).join("") || `<div class="hint">nothing yet</div>`}</div>
    <div class="chatbar">
      <input id="chatIn" placeholder="message ${esc(title)}" autocomplete="off"
        aria-label="message">
      <button type="button" class="primary" id="chatSend">Send</button>
    </div>`);
  const inp = el.querySelector("#chatIn");
  inp.value = chatDraft[key] || "";
  inp.oninput = () => { chatDraft[key] = inp.value; };
  const send = async () => {
    const text = inp.value;
    if (!text.trim()) return;
    inp.value = ""; chatDraft[key] = "";
    try{
      const r = await (await fetch("/api/chat", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "send", ...chatWith, text }) })).json();
      if (r.error){ notify(r.error, true); inp.value = text; chatDraft[key] = text; }
      else { chatMsgs = r.messages || []; drawChat(); }
    }catch(e){ inp.value = text; chatDraft[key] = text; }
  };
  inp.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); send(); } };
  el.querySelector("#chatSend").onclick = send;
  el.querySelector("#chatBack").onclick = e => { e.stopPropagation(); chatWith = null; chatDrawn = ""; drawChat(); };
  // Newest last, and a reader at the end wants the newest: pinned to the
  // bottom the way the job logs are. One who scrolled up stays where they were.
  const log = el.querySelector("#chatlog");
  if (log) log.scrollTop = atEnd ? log.scrollHeight : keep;
}

async function sendKey(key){
  const t = tabOf(panes[active]);
  if (!t || t.kind !== "term") return;
  // BuilderBot's own terminal takes the key down its own socket, as typed
  // (R133 step 5); PgUp and PgDn still ask the server, which knows whether
  // tmux is on the alternate screen and opens copy mode when it is not.
  if (termOwn(t) && termKey(t, key)) return;
  try{
    const r = await postJSON("/api/keys", {session: sessionOf(t.arg), key});
    const j = await r.json();
    if (j.error) notify("key: " + j.error, true);
  }catch(e){ notify("key failed: " + failWords(e), true); }
}
