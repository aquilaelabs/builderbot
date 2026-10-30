// The Phone tab: a handset on wireless adb, driven from a node picked in its
// bar (R121, the operator 4 Oct: inside a node's page it was hard to find,
// and the Nodes tab is a machine's configuration). Several nodes may each
// carry adb and hold a phone; the picker lists those, and the panel below is
// the picked one's. Its own classic script beside index.html.
//
// The controller has no adb and holds no phone. Every node whose census
// reports adb is a place a phone can be paired and connected, each holding
// its own, and every press in its section is a job on that node, waited for.
//
// One owner per connection. Whoever connects a phone is the only account
// that can disconnect it, and the only one asked when a session wants to
// touch it. Everybody else sees the connection with its controls grayed and
// the owner named: the phone is on somebody's desk, and they are the one
// who said yes to it.
//
// Fetched on demand rather than on the fifteen-second poll: a probe is a job
// on the node, so the tab asks when it is opened or pressed, and the server
// answers from its cache in between.

"use strict";

let ph = null, phBusy = "", phRev = 0, phFetching = false, phRefreshing = false;
let phNode = "";                 // the picked node's id; "" until the first answer
// Held outside the render, because the tab is rebuilt whole on every draw and
// a field that emptied itself mid-sentence would be unusable.
let phIp = "", phPort = "", phCode = "", phConnPort = "";
let phFoot = "";                 // the lease, said at the page's foot
// The lend controls' picks, kept across a redraw (R113).
let phLendTo = "", phLendFor = "1";

// The Phone tab, on the node that holds a phone (or the first that can).
function openPhoneTab(){
  const n = (ph?.nodes || []).find(x => x.phone);
  if (n && !phNode) phNode = n.id;
  openTab({kind: "phone", arg: "__phone", label: "Phone"});   // the kind's open hook probes
}

// Check now, on the phone's own row under the header (the operator, 29
// Oct: the bar it stood in left a gap over the page); the node is the
// Build group's header's (R178), so the bar carries nothing.
function phoneCheckBtn(ghost){
  return `<button type="button"${ghost ? " disabled" : ` id="phRefresh"`} title="ask the node's adb about the phone now">Check now</button>`;
}

function renderPhoneInto(i){
  const d = docSurface(i, "phone");
  if (!d) return;
  if (!ph){
    // Its template (R218 step 16): the state row's words and the two ways in
    // (connect, pair) with their labels are the page's own; the node and
    // its phone are on their way.
    const fld = (label, em, grow = false) => skField(label, em, grow ? "grow" : "");
    d.setBar("");
    // In the card the rows land in (.phonetab).
    d.list.innerHTML = skTpl(`<div class="phonetab"><div class="row toolstate"><div class="grow"><div class="name">Phone ${skv(6)}</div>
        <div class="sub">${skv(10)}</div></div><span class="acts actbar">${phoneCheckBtn(true)}</span></div>
      <div class="row">${fld("Phone IP address", 18, true)}${fld("Port", 7)}<span class="acts"><button type="button" class="primary" disabled>Connect</button></span></div>
      <div class="row"><div class="grow prefrow ctlrow">${fld("Pairing port", 9)}${fld("Pairing code", 9)}</div>
        <span class="acts"><button type="button" disabled>Pair</button></span>
        <div class="sub">On the phone: Wireless debugging, then <b>Pair device with pairing code</b>. Keep that dialog open.</div></div></div>`);
    return;
  }
  const nodes = ph.nodes || [];
  // The node the Build group's header picked (R178): one without adb is
  // said so, not swapped for the first that has it.
  const picked = (nodesList || []).find(x => x.id === phNode);
  const n = nodes.find(x => x.id === phNode) || (!phNode ? nodes[0] : null);
  d.setBar("");
  phFoot = "";
  d.list.innerHTML = n ? phonePanel(n)
    : picked ? `<div class="hint">${esc(picked.name)} has no adb: install Android platform tools on it from the ${pageLink("library", "Library")}.</div>`
    : `<div class="hint">No node carries adb yet: install Android platform tools on one from the ${pageLink("library", "Library")}.</div>`;
  d.setFoot(phFoot);
  if (!tcDotsTimer && d.list.querySelector(".dots")) tcDotsTimer = setInterval(tcTickDots, 400);
  wirePhoneTab(d.el);
}

// Connecting, pairing and disconnecting are any account's: a phone is its
// owner's, not the administrators': whoever connects one is the only
// account that can disconnect it or answer a session asking for it, and
// the server holds that. Kept as a function so the call sites read as the
// question they ask.
const mayPhone = () => true;

async function phFetch(body, probe){
  const knew = phNode;
  // An answer leaves the list the moment it is given (B641): the server
  // drops an allowed or denied ask at once, but this request returns only
  // when what was allowed has run, which for a root command is minutes.
  // The answer that comes back is the list either way.
  if (body && (body.action === "allow" || body.action === "deny") && ph?.asks){
    ph.asks = ph.asks.filter(a => a.id !== body.id);
    phRev++;
    if (tabs.some(t => ["phone", "nodes", "docker"].includes(t.kind))) drawPanes();
    drawBell();
  }
  try{
    const q = `?node=${encodeURIComponent(phNode)}${probe ? "&probe=1" : ""}`;
    const r = body
      ? await fetch("/api/phone", {method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({node: phNode, ...body})})
      : await fetch("/api/phone" + q);
    const j = await r.json();
    if (j.error){ notify(j.error, true); if (!ph) return; }
    else ph = j;
  // A read of its own that met a controller not answering is the poll's to
  // say (its light and the line under the header), not a failure to keep;
  // a press is told either way (B301).
  }catch(e){ if (body || !unreached(e)) notify("phone: " + failWords(e), true); }
  phBusy = ""; phRefreshing = false;
  if (ph && !ph.nodes.some(n => n.id === phNode)) phNode = ph.nodes[0]?.id || "";
  // A probe asked for before any node was known went nowhere: now one is,
  // ask it once.
  if (probe && !body && !knew && phNode) return phFetch(null, true);
  phRev++;
  // The Nodes tab draws the root asks from the same answer, and the Docker
  // tab the rebuild ones.
  if (tabs.some(t => ["phone", "nodes", "docker"].includes(t.kind))) drawPanes();
  drawBell();          // the same asks, in the header
}

// Why Connect or Pair cannot be pressed, said under its row in red (B114:
// both sat dead with the reason only in a tooltip, which a phone never
// shows): whose the phone is or that the node is away, else what is still
// to be typed. "" when the press is ready.
function phWhy(which, offWhy){
  if (offWhy) return offWhy;
  const need = [!phIp.trim() && "the phone's IP address",
                which === "connect" ? !phConnPort.trim() && "its port" : !phPort.trim() && "the pairing port",
                which === "pair" && !phCode.trim() && "the pairing code"].filter(Boolean);
  return need.length ? `${which === "connect" ? "Connect" : "Pair"} needs ${
    need.length > 1 ? need.slice(0, -1).join(", ") + " and " + need.at(-1) : need[0]}` : "";
}
const phWhyLine = (which, offWhy) => {
  const why = phWhy(which, offWhy);
  return `<div class="sub warn phwhy" data-phwhy="${which}"${why ? "" : " hidden"}>${why}</div>`;
};

// The section's body for one node: its phone, connecting and pairing, the
// lease, the phones it remembers, and what a session waits on. `n` is that
// node's row in the phone answer (ph.nodes).
function phonePanel(n){
  if (!ph) return `${skel("rows", 3)}`;
  phNode = n.id;
  const dev = n?.phone;
  const asks = (ph.asks || []).filter(a => a.kind !== "root" && (!a.node || a.node === n.id));
  // This browser's own address wins when it is the phone: viewing the
  // dashboard ON the device is the one case where the number is not something
  // anybody has to go and read. The node's remembered IP is the fallback.
  if (!phIp) phIp = ph.you || n?.ip || "";
  const held = n && n.owner && !n.mine;   // somebody else's connection
  // ...or this install switched pairing a phone off (R81).
  const off = held || !n.live || !mayPhone() || !!featureOff("phone");
  const offWhy = featureOff("phone") ? esc(featureOff("phone"))
    : held ? `connected by ${esc(n.owner.name)}: only they can change it`
    : !n.live ? "the node is not dialing in"
    : "";
  // A word and an animated ellipsis, never a bar: nothing here knows a
  // percentage, and inventing one would be a lie about progress.
  const pill = phBusy
    ? `<span class="pill go">${esc(phBusy)}<span class="dots"></span></span>`
    : dev ? `<span class="pill stat ok">connected</span> <span class="pill">${esc(dev.model || "phone")}</span>`
          : `<span class="pill stat">not connected</span>`;
  // The node-scoped tool's shape, the CI runner tab's too (R121 step 5):
  // the state row first, then the ways in, what it is lent to and what it
  // remembers, and at the foot how a session reaches it.
  const rows = [
    `<div class="row toolstate">
       <div class="grow"><div class="name">Phone ${pill}${
           n.owner ? ` <span class="dim">· connected by ${esc(n.owner.name)}${n.mine ? " (you)" : ""}</span>` : ""}</div>
         <div class="sub">${!n.live
           ? `${esc(n.name)} is not dialing in; nothing reaches its adb right now`
           : dev ? (dev.serial ? esc(dev.serial) : `connected by ${esc(n.owner?.name || "somebody")}; which phone is theirs to know`)
           : "no phone on its adb"}</div></div>
       <span class="acts actbar">${phoneCheckBtn(false)}${dev && (n.mine || state?.admin) && mayPhone() ? `<button type="button" id="phDisconnect"${
         n.mine ? "" : ` data-other="${esc(n.owner?.name || "somebody")}"`}
         >Disconnect</button>` : ""}</span>
     </div>`,
    // An IP and its port, both read off the phone's wireless debugging
    // screen. Android hands out a new port every time wireless debugging is
    // toggled; the node used to scan the phone for it, which across a VPN is
    // what a network flags as port scanning (the operator, 9 Oct).
    `<div class="row">
       <div class="grow setrow col ctlrow">${lbl("phIp", "Phone IP address", "from its wireless debugging screen, before the colon")}
         <input id="phIp" maxlength="15" autocomplete="off"
         placeholder="192.168.0.10" value="${esc(phIp)}"${off ? " disabled" : ""}></div>
       <div class="setrow col ctlrow">${lbl("phConnPort", "Port", "after the colon on the wireless debugging screen; it changes each time that is turned on")}
         <input id="phConnPort" maxlength="5" inputmode="numeric" autocomplete="off"
         placeholder="41235" value="${esc(phConnPort)}"${off ? " disabled" : ""}></div>
       <span class="acts"><button type="button" id="phConnect" class="primary"${off ? ' data-off="1"' : ""}${
         off || !phIp.trim() || !phConnPort.trim() ? " disabled" : ""} title="${offWhy}"
         >${dev ? "Reconnect" : "Connect"}</button></span>
       ${phWhyLine("connect", offWhy)}
       ${ph.you && phIp === ph.you
         ? `<div class="sub">this device; you are reading this on it</div>`
         // The hint under the control it is about (R218 step 23).
         : !dev ? `<div class="sub">try Connect first: a pairing outlives a restart</div>` : ""}
     </div>`,
    // Pairing in the open rather than behind a fold: it is two fields, and a
    // fold over two fields is a click that buys nothing.
    `<div class="row">
       <div class="grow prefrow ctlrow">
         <div class="setrow col ctlrow">${lbl("phPairPort", "Pairing port", "from the pairing dialog, not the main screen")}
         <input id="phPairPort" maxlength="5" autocomplete="off" placeholder="37123"
           value="${esc(phPort)}"${off ? " disabled" : ""}></div>
         <div class="setrow col ctlrow">${lbl("phPairCode", "Pairing code")}
         <input id="phPairCode" maxlength="6" autocomplete="off" placeholder="123456"
           value="${esc(phCode)}"${off ? " disabled" : ""}></div>
       </div>
       <span class="acts"><button type="button" id="phPair"${off ? ' data-off="1"' : ""}${
         off || !phIp.trim() || !phPort.trim() || !phCode.trim() ? " disabled" : ""} title="${offWhy}">Pair</button></span>
       ${phWhyLine("pair", offWhy)}
       <div class="sub">${ph.you && phIp === ph.you
         ? `<b class="warn">You are reading this on the phone you are pairing.</b>
            Pair from another device: Android closes the pairing dialog when you leave it.`
         : `On the phone: Wireless debugging, then <b>Pair device with pairing code</b>.
            Keep that dialog open.`}</div>
     </div>`,
  ];
  // What a session is waiting on, above everything else it could be doing:
  // somebody is blocked on it, and that somebody asked YOU: a request only
  // ever reaches the account that connected the phone it is about.
  // First after the state row, as said (R218 step 23): they were pushed last.
  rows.splice(1, 0, ...asks.map(a => `<div class="row phask">
      <div class="grow"><div class="name">${esc(a.why)}</div>
        <div class="phcmd">${askCmd(a)}</div>
        <div class="sub">${esc(askWho(a))} on ${esc(a.node_name)} · ${askLeft(a)}</div></div>
      <span class="acts">${askActs({...a, kind: "phone"}, {deny: "data-deny", allow: "data-allow"})}</span></div>`));
  // Lent to a project (R113): its sessions drive that project's own app on
  // the phone with no ask per command, and the owner watches and takes it
  // back here. The lend controls are the owner's; everybody sees the lease.
  const L = n.lease;
  if (dev && L){
    const left = L.left === null || L.left === undefined ? "until taken back"
      : L.left > 3600 ? `${Math.floor(L.left / 3600)} h ${Math.round((L.left % 3600) / 60)} min left`
      : `${Math.max(1, Math.round(L.left / 60))} min left`;
    rows.push(`<div class="row phlease">
       <div class="grow"><div class="name">Lent to ${esc(projLabel(L.project))} <span class="pill go">${esc(left)}</span></div>
         <div class="sub">${(L.pkgs || []).length
           ? `its sessions drive ${esc(L.pkgs.join(", "))}, and nothing else, without asking`
           : "its sessions may install one of its builds; then that app, and nothing else, without asking"}</div>${
         L.shot ? `<img class="phshot" alt="the phone's screen, as last seen" src="/api/artifact?project=${
           encodeURIComponent(L.project)}&path=${encodeURIComponent(L.shot)}">
           <div class="sub">${esc(L.shot.split("/").pop())}</div>` : ""}${
         // The newest recording as its reel: the frames that changed, each
         // with its time, in one picture, and the video itself a link away
         // (the operator, 5 Oct).
         L.reel ? `<div class="phreelbox"><img class="phreel" alt="the newest recording, as the frames that changed with their times" src="/api/artifact?project=${
           encodeURIComponent(L.project)}&path=${encodeURIComponent(L.reel)}"></div>
           <div class="sub">${esc(L.reel.split("/").pop())}${L.video ? ` · <a href="/api/artifact?project=${
             encodeURIComponent(L.project)}&path=${encodeURIComponent(L.video)}" target="_blank" rel="noopener">the video</a>` : ""}</div>` : ""}${
         L.recording ? `<div class="sub"><span class="pill warn">recording</span> a session is recording the screen</div>` : ""}
         ${n.mine ? `<div class="actbar"><span class="state">the screen updates as a session takes shots and recordings</span>
           <button type="button" id="phLook">Look now</button>
           <button type="button" class="danger" id="phTakeBack">Take back</button></div>` : ""}</div>
     </div>`);
  } else if (dev && n.mine && mayPhone()){
    const ps = n.lendable || [];
    rows.push(`<div class="row phlend">
       <div class="grow">
         <div class="name">Lend to a project</div>
         <div class="prefrow ctlrow">
           <label class="pick">Project <select id="phLendTo" aria-label="the project to lend the phone to"${ps.length ? "" : " disabled"}>${
             optionList(ps.map(p => [p, projLabel(p)]), phLendTo)}</select></label>
           <label class="pick">For <select id="phLendFor" aria-label="how long">
             <option value="1"${phLendFor === "1" ? " selected" : ""}>1 hour</option>
             <option value="4"${phLendFor === "4" ? " selected" : ""}>4 hours</option>
             <option value="0"${phLendFor === "0" ? " selected" : ""}>until taken back</option></select></label>
         </div>
         <div class="actbar"><span class="state">its sessions then install, run, see and touch its own app here without asking; anything else still asks you</span>
           <button type="button" id="phLend"${ps.length ? "" : " disabled"}>Lend</button></div>
         ${ps.length ? "" : `<div class="sub bad">No project of yours runs on ${esc(n.name)}, so there is none to lend it to.</div>`}
       </div></div>`);
  }
  // The phones this node has paired or connected, newest first. The pairing
  // outlives everything (the key is in the node account's ~/.android), so a
  // remembered phone is one press: its address goes in the field above and
  // the node finds the port. Forget drops the memory, not the pairing.
  const known = (n.known || []).filter(k => k.ip);
  if (known.length)
    rows.push(`<div class="row"><div class="grow">
        <div class="name">Remembered on ${esc(n.name)}</div>
        <div class="sub">paired or connected here before: today's port is all they need</div>
        <div class="sub note phknownsay"${phConnPort.trim() ? " hidden" : ""}>Connect wakes once today's port is typed in Port above</div>
      </div></div>`,
      ...known.map(k => `<div class="row phknown" data-ip="${esc(k.ip)}">
        <div class="grow">
          <div class="name">${esc(k.model || k.ip)}${
            dev && (dev.serial === k.serial || (dev.model && dev.model === k.model))
              ? ` <span class="pill ok">connected</span>` : ""}</div>
          <div class="sub">${esc(k.ip)}${k.model ? "" : " · paired, never connected from here"} · ${
            esc(ago(k.last || k.first || 0))}${k.by ? ` by ${esc(k.by)}` : ""}</div>
          <div class="actbar">
            <button type="button" data-kconnect="${esc(k.ip)}"${off ? ' data-off="1"' : ""}${off || !phConnPort.trim() ? " disabled" : ""} title="${offWhy}">Connect</button>
            <button type="button" class="danger" data-kforget="${esc(k.ip)}">Forget</button>
          </div>
        </div></div>`));
  // What the owner allowed for a session (the operator, 4 Oct): its
  // commands to this phone run without asking until this is taken back,
  // the lease ends or the phone is disconnected.
  for (const g of (n.trust || []))
    rows.push(`<div class="row phtrust">
      <div class="grow"><div class="name">Allowed for ${esc(g.asker || "a")}'s sessions in ${esc(projLabel(g.project))}</div>
        <div class="sub">their commands to this phone run without asking ${g.until
          ? `until ${esc(fmtTime(g.until * 1000, {hour: "2-digit", minute: "2-digit"}))}`
          : "while it is lent to " + esc(g.project)}</div></div>
      <span class="acts"><button type="button" data-untrust="${esc(g.project)}" data-asker="${esc(g.asker_uid || "")}">Ask every time</button></span>
    </div>`);
  const L2 = n.lease;
  // Refresh is the tab's bar's (R121); a lease is said at the foot, and
  // nothing else is (the operator, 16 Oct: how it works is the docs' to say).
  // At the page's foot, through setFoot (R218 step 23).
  phFoot = L2 ? `<span class="phbar">Lent to ${esc(projLabel(L2.project))}: each command its sessions run on its own app asks ${esc(n.owner?.name || "its owner")} first, unless allowed for the session.</span>` : "";
  if (!tcDotsTimer && rows.join("").includes('class="dots"')) tcDotsTimer = setInterval(tcTickDots, 400);
  return `<div class="phonetab">${rows.join("")}</div>`;
}

function wirePhoneTab(root){
  const $$ = id => root.querySelector("#" + id);
  const rf = $$("phRefresh");
  // Refresh says so on the button itself, like every other tab's (the
  // operator, 13 Oct); the pill is for what the phone is being asked to do.
  if (rf) rf.onclick = () => { phRefreshing = true; busy(rf, "Refreshing"); phFetch(null, true); };
  if (rf && phRefreshing) busy(rf, "Refreshing");
  // The fields keep what is in them across a redraw.
  const keep = (id, set) => { const el = $$(id); if (el) el.oninput = e => set(e.target.value); };
  // Each press wakes once what it sends is typed (the operator, 18 Oct): a
  // press that only said what was missing was asleep in all but look.
  const wake = () => {
    const set = (b, ready) => { if (b) b.disabled = b.dataset.off === "1" || !ready; };
    set($$("phConnect"), phIp.trim() && phConnPort.trim());
    set($$("phPair"), phIp.trim() && phPort.trim() && phCode.trim());
    root.querySelectorAll("[data-kconnect]").forEach(b => set(b, phConnPort.trim()));
    // ...and the reason under each row follows what is typed.
    root.querySelectorAll("[data-phwhy]").forEach(el => {
      const b = $$(el.dataset.phwhy === "connect" ? "phConnect" : "phPair");
      if (b?.dataset.off === "1") return;
      const why = phWhy(el.dataset.phwhy, "");
      el.textContent = why; el.hidden = !why;
    });
    const say = root.querySelector(".phknownsay");
    if (say) say.hidden = !!phConnPort.trim();
  };
  keep("phIp", v => { phIp = v; wake(); });
  keep("phConnPort", v => { phConnPort = v; wake(); });
  keep("phPairPort", v => { phPort = v; wake(); });
  keep("phPairCode", v => { phCode = v; wake(); });
  const on = (id, fn) => { const el = $$(id); if (el) el.onclick = fn; };
  on("phConnect", () => {
    if (!phIp.trim()) return notify("the phone's IP, from its wireless debugging screen", true);
    if (!phConnPort.trim()) return notify("the port too: after the colon under IP address & port on its wireless debugging screen", true);
    phBusy = "connecting"; phRev++; drawPanes();
    phFetch({action: "connect", ip: phIp.trim(), port: phConnPort.trim()});
  });
  on("phDisconnect", async () => {
    // An administrator ending somebody else's connection is told whose it
    // is, and that its lease goes with it (R120).
    const other = document.getElementById("phDisconnect")?.dataset.other;
    if (other && !await askYes(`Disconnect ${other}'s phone? Its lease to a project ends too.`)) return;
    phBusy = "disconnecting"; phRev++; drawPanes();
    phFetch({action: "disconnect"});
  });
  on("phPair", () => {
    phBusy = "pairing"; phRev++; drawPanes();
    phFetch({action: "pair", ip: phIp.trim(), port: phPort.trim(), code: phCode.trim()});
  });
  root.querySelectorAll("[data-kconnect]").forEach(b => b.onclick = () => {
    phIp = b.dataset.kconnect;
    // Its port is today's, on the phone: asked for rather than guessed.
    if (!phConnPort.trim()){
      drawPanes();
      $$("phConnPort")?.focus();
      return notify("type today's port: after the colon under IP address & port on its wireless debugging screen", true);
    }
    phBusy = "connecting"; phRev++; drawPanes();
    phFetch({action: "connect", ip: phIp, port: phConnPort.trim()});
  });
  root.querySelectorAll("[data-kforget]").forEach(b => b.onclick = () =>
    phFetch({action: "forget", ip: b.dataset.kforget}));
  root.querySelectorAll("[data-allow]").forEach(b => b.onclick = () => {
    phBusy = "running it"; phRev++; drawPanes();
    phFetch({action: "allow", id: Number(b.dataset.allow), session: !!b.dataset.session});
  });
  root.querySelectorAll("[data-untrust]").forEach(b => b.onclick = () =>
    phFetch({action: "untrust", project: b.dataset.untrust, asker_uid: b.dataset.asker || ""}));
  root.querySelectorAll("[data-deny]").forEach(b => b.onclick = () =>
    phFetch({action: "deny", id: Number(b.dataset.deny)}));
  const lt = $$("phLendTo"), lf = $$("phLendFor");
  if (lt) lt.onchange = () => { phLendTo = lt.value; };
  if (lf) lf.onchange = () => { phLendFor = lf.value; };
  on("phLend", () => {
    const project = lt?.value || "";
    if (!project) return notify("pick the project to lend it to", true);
    phBusy = "lending"; phRev++; drawPanes();
    phFetch({action: "lend", project, hours: Number(lf?.value || 1)});
  });
  on("phTakeBack", () => { phBusy = "taking it back"; phRev++; drawPanes(); phFetch({action: "take-back"}); });
  on("phLook", () => { phBusy = "looking"; phRev++; drawPanes(); phFetch({action: "look"}); });
}
