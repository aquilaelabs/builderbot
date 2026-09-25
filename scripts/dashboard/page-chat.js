// Chat: the messages between people and sessions on a project, read and
// sent from the sidebar's Chat button.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

let chatWith = null;                 // {who} or {project}, or null for the list
let chatMsgs = [], chatDraft = {}, chatSeenRev = -1, chatTimer = null;
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

// While the panel is open, faster than the fifteen-second poll: a chat at
// that cadence is a message board. Only while it is open: this is the one
// surface that wants a tighter loop and it should not cost anything when it
// is shut.
function chatLoop(){
  clearInterval(chatTimer);
  chatTimer = showChat ? setInterval(loadChat, 4000) : null;
}

function chatOpen(w){ chatWith = w; chatMsgs = []; chatDrawn = ""; loadChat(); chatLoop(); }

function drawChat(){
  const el = $("chat");
  if (!el) return;
  chatLoop();
  const c = state?.chat;
  if (!c || !c.people) return paint(el, `<div class="empty">sign in to chat</div>`);
  const unread = c.unread || {};
  if (!chatWith){
    const here = new Set(c.online || []);
    const people = (c.people || []).map(n =>
      `<button class="row chatrow" data-who="${esc(n)}">
         <span class="dot ${here.has(n) ? "ok" : ""}"></span>
         <span class="grow">${esc(n)}</span>
         ${unread["dm:" + n] ? `<span class="pill">${unread["dm:" + n]}</span>` : ""}
       </button>`);
    // A project channel is the group chat for everybody on it, and it is where
    // the Claude sessions and the prompts land. An ADMIN is shown every one;
    // they are shown every project (roadmap #27) and the same rule decides
    // this, with the ones they have actually taken on marked and sorted
    // first, so "mine" and "everything else on the box" are one glance apart
    // rather than one read of a list of forty.
    const ps = [...(state?.projects || [])]
      .sort((a, b) => (notMine(a) - notMine(b)) || a.name.localeCompare(b.name));
    const projs = ps.map(p => {
      // Unread is only ever marked on a channel that is YOURS. An admin is
      // shown every project's channel and most are somebody else's business:
      // colouring those would be a page permanently asking to be read.
      const n = notMine(p) ? 0 : unread["p:" + p.name] || 0;
      return `<button class="row chatrow${notMine(p) ? " notmine" : ""}${
        n ? " unread" : ""}" data-proj="${esc(p.name)}"
         ${notMine(p) ? `title="you have not taken this project on; you can read it"` : ""}>
         <span class="grow">#${esc(p.name)}</span>
         ${n ? `<span class="pill">${n}</span>` : ""}
       </button>`;
    });
    const mine = ps.filter(p => !notMine(p)).length;
    paint(el, (people.length ? people.join("") : `<div class="empty">no other accounts</div>`)
      + (projs.length ? `<div class="sub chathead">projects${
           mine < ps.length ? `, yours first` : ""}</div>` + projs.join("") : ""));
    el.querySelectorAll("[data-who]").forEach(b =>
      b.onclick = () => chatOpen({ who: b.dataset.who }));
    el.querySelectorAll("[data-proj]").forEach(b =>
      b.onclick = () => chatOpen({ project: b.dataset.proj }));
    return;
  }
  const title = chatWith.project ? "#" + chatWith.project : chatWith.who;
  const key = chatKey(chatWith);
  // Painted only when the conversation changed: the poll every four seconds
  // repainted the panel whole and pinned the log to its end, and a reader
  // scrolled up to an older message was dragged back down each time (the
  // operator, 25 Sep). And when it is painted, the reader keeps their place
  // unless they were at the end, where the newest message is what they want.
  // The minute is in it so "3 min ago" still moves, once a minute.
  const sig = key + "\n" + Math.floor(Date.now() / 60000) + "\n"
    + chatMsgs.map(m => `${m.at}\t${m.who}\t${m.kind}\t${m.text}`).join("\n");
  if (sig === chatDrawn && el.querySelector("#chatlog")) return;
  chatDrawn = sig;
  const was = el.querySelector("#chatlog");
  const atEnd = !was || was.scrollTop + was.clientHeight >= was.scrollHeight - 8;
  const keep = was ? was.scrollTop : 0;
  paint(el, `
    <div class="chathead">
      <button class="link" id="chatBack">‹ all</button>
      <b class="grow">${esc(title)}</b>
    </div>
    ${chatWith.project ? `<div class="sub chatnote">everyone on this project sees this</div>` : ""}
    <div class="chatlog" id="chatlog">${chatMsgs.map(m => `
      <div class="chatmsg${m.kind === "did" || m.kind === "asked" ? " ev" : ""}">
        <span class="dim">${esc(m.who || "?")} · ${ago(m.at)}</span>
        <div>${esc(m.text)}</div>
      </div>`).join("") || `<div class="empty">nothing yet</div>`}</div>
    <div class="chatbar">
      <input id="chatIn" placeholder="message ${esc(title)}" autocomplete="off"
        aria-label="message">
      <button class="primary" id="chatSend">Send</button>
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
  el.querySelector("#chatBack").onclick = () => { chatWith = null; chatDrawn = ""; drawChat(); };
  // Newest last, and a reader at the end wants the newest: pinned to the
  // bottom the way the job logs are. One who scrolled up stays where they were.
  const log = el.querySelector("#chatlog");
  if (log) log.scrollTop = atEnd ? log.scrollHeight : keep;
}

async function sendKey(key){
  const t = tabOf(panes[active]);
  if (!t || t.kind !== "term") return;
  try{
    const r = await postJSON("/api/keys", {session: sessionOf(t.arg), key});
    const j = await r.json();
    if (j.error) notify("key: " + j.error, true);
  }catch(e){ notify("key failed: " + e, true); }
}
