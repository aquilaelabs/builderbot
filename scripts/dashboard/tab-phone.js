// The Phone tab: a handset on wireless adb, driven from a node. Its own
// classic script beside index.html, per the new-surface rule: same page,
// same global scope, one file per surface. Chrome comes from docSurface()
// and the hard rules are held by uniform.mjs — this file only fills slots.
//
// The controller has no adb and holds no phone. Every node whose census
// reports adb is a place a phone can be paired and connected, each holding
// its own; the picker in the bar says which one this tab is about, and every
// press below it is a job on that node, waited for.
//
// One owner per connection. Whoever connects a phone is the only account
// that can disconnect it, and the only one asked when a session wants to
// touch it. Everybody else sees the connection with its controls greyed and
// the owner named — the phone is on somebody's desk, and they are the one
// who said yes to it.
//
// Fetched on demand rather than on the fifteen-second poll: a probe is a job
// on the node, so the tab asks when it is opened or pressed, and the server
// answers from its cache in between.
let ph = null, phBusy = "", phRev = 0;
let phNode = "";                 // the picked node's id; "" until the first answer
// Held outside the render, because the tab is rebuilt whole on every draw and
// a field that emptied itself mid-sentence would be unusable.
let phIp = "", phPort = "", phCode = "";

function openPhoneTab(){
  openTab({kind: "phone", arg: "__phone", label: "Phone"});   // the kind's open hook probes
}

// Connecting, pairing and disconnecting are any account's: a phone is its
// owner's, not the administrators' — whoever connects one is the only
// account that can disconnect it or answer a session asking for it, and
// the server holds that. Kept as a function so the call sites read as the
// question they ask.
const mayPhone = () => true;

async function phFetch(body, probe){
  const knew = phNode;
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
  }catch(e){ notify("phone: " + e, true); }
  phBusy = "";
  if (ph && !ph.nodes.some(n => n.id === phNode)) phNode = ph.nodes[0]?.id || "";
  // A probe asked for before any node was known went nowhere: now one is,
  // ask it once.
  if (probe && !body && !knew && phNode) return phFetch(null, true);
  phRev++;
  // The Nodes tab draws the root asks from the same answer.
  if (tabs.some(t => t.kind === "phone" || t.kind === "nodes")) drawPanes();
  drawBell();          // the same asks, in the header
}

function renderPhoneInto(i){
  const d = docSurface(i, "phone");
  if (!d) return;
  if (!ph){
    d.list.innerHTML = `<div class="loading">loading…</div>`;
    return;
  }
  // The root asks share the list (one bell, one fetch) and are the Nodes
  // tab's to show: they are about a machine, not a handset.
  const nodes = ph.nodes || [], asks = (ph.asks || []).filter(a => a.kind !== "root");
  const n = nodes.find(x => x.id === phNode) || nodes[0];
  const dev = n?.phone;
  // This browser's own address wins when it is the phone: viewing the
  // dashboard ON the device is the one case where the number is not something
  // anybody has to go and read. The node's remembered IP is the fallback.
  if (!phIp) phIp = ph.you || n?.ip || "";
  if (!nodes.length){
    d.setBar(`<span class="sp"></span>
      <button type="button" id="phRefresh" title="ask again now">Refresh</button>`);
    d.list.innerHTML = `<div class="hint">No node carries adb. A phone is driven from
      a node — install android-tools on one from the Tools tab, and it appears here.</div>`;
    wirePhoneTab(d.el);
    return;
  }
  const held = n && n.owner && !n.mine;   // somebody else's connection
  const off = held || !n.live || !mayPhone();
  const offWhy = held ? `connected by ${esc(n.owner.name)} — only they can change it`
    : !n.live ? "the node is not dialing in"
    : "";
  d.setBar(`${nodes.length ? `<label class="pick">Node <select id="phPick" aria-label="node">${
      nodes.map(x => `<option value="${esc(x.id)}"${x.id === n?.id ? " selected" : ""}>${
        esc(x.name)}${x.phone ? ` — ${esc(x.phone.model || "phone")}` : ""}${
        x.live ? "" : ", quiet"}</option>`).join("")}</select></label>` : ""}
    <span class="sp"></span>
    <button type="button" id="phRefresh" title="ask the node's adb again now">Refresh</button>`);
  // A word and an animated ellipsis, never a bar: nothing here knows a
  // percentage, and inventing one would be a lie about progress.
  const state = phBusy
    ? `<span class="pill go">${esc(phBusy)}<span class="dots"></span></span>`
    : dev ? `<span class="pill ok">${esc(dev.model || "phone")}</span>`
          : `<span class="pill">not connected</span>`;
  const rows = [
    `<div class="row">
       <div class="grow"><div class="name">${state}${
           n.owner ? ` <span class="dim">· connected by ${esc(n.owner.name)}${n.mine ? " (you)" : ""}</span>` : ""}</div>
         <div class="sub">${!n.live
           ? `${esc(n.name)} is not dialing in — nothing reaches its adb right now`
           : dev ? esc(dev.serial)
           : "try Connect first — a pairing outlives a restart, so it is usually already done"}</div></div>
       ${dev && n.mine && mayPhone() ? `<span class="acts"><button type="button" id="phDisconnect"
         >Disconnect</button></span>` : ""}
     </div>`,
    // An IP and no port. Android hands out a new connect port every time
    // wireless debugging is toggled, so the node scans for it rather than
    // sending anybody back to the phone to read a number that has changed.
    `<div class="row">
       <div class="grow setrow col">${lbl("phIp", "Phone IP address", "from its wireless debugging screen. The port is found for you")}
         <input id="phIp" maxlength="15" autocomplete="off"
         placeholder="192.168.0.10" value="${esc(phIp)}"${off ? " disabled" : ""}></div>
       <span class="acts"><button type="button" id="phConnect" class="primary"${
         off ? " disabled" : ""} title="${offWhy}"
         >${dev ? "Reconnect" : "Connect"}</button></span>
       ${ph.you && phIp === ph.you
         ? `<div class="sub">this device — you are reading this on it</div>` : ""}
     </div>`,
    // Pairing in the open rather than behind a fold: it is two fields, and a
    // fold over two fields is a click that buys nothing.
    `<div class="row">
       <div class="grow prefrow">
         <div class="setrow col">${lbl("phPairPort", "Pairing port", "from the pairing dialog, not the main screen")}
         <input id="phPairPort" maxlength="5" autocomplete="off" placeholder="37123"
           value="${esc(phPort)}"${off ? " disabled" : ""}></div>
         <div class="setrow col">${lbl("phPairCode", "Pairing code")}
         <input id="phPairCode" maxlength="6" autocomplete="off" placeholder="123456"
           value="${esc(phCode)}"${off ? " disabled" : ""}></div>
       </div>
       <span class="acts"><button type="button" id="phPair"${off ? " disabled" : ""} title="${offWhy}">Pair</button></span>
       <div class="sub">${ph.you && phIp === ph.you
         ? `<b class="warn">You are reading this on the phone you are pairing.</b>
            Android closes the pairing dialog the moment you leave it, and the
            port goes with it — so pair from another device with that dialog
            open here, or skip it: pairing is once per node, and Connect is
            all you need after that.`
         : `Wireless debugging → <b>Pair device with pairing code</b>, and
            leave that dialog open — it cancels when you navigate away. Its
            port is not the one the main screen shows.`}</div>
     </div>`,
  ];
  // What a session is waiting on, above everything else it could be doing:
  // somebody is blocked on it, and that somebody asked YOU — a request only
  // ever reaches the account that connected the phone it is about.
  for (const a of asks)
    rows.push(`<div class="row phask">
      <div class="grow"><div class="name">${esc(a.why)}</div>
        <div class="phcmd">adb ${esc(a.cmd.join(" "))}</div>
        <div class="sub">${esc(a.asker ? a.asker + "'s session in " + (a.project || "a project") : a.project || "a session")} on ${esc(a.node_name)} · ${a.left > 60
          ? `${Math.floor(a.left / 60)} min left to answer`
          : `${a.left}s left to answer`}</div></div>
      <span class="acts">
        <button type="button" data-deny="${a.id}">Deny</button>
        <button type="button" class="primary" data-allow="${a.id}">Allow</button>
      </span></div>`);
  d.list.innerHTML = rows.join("");
  d.setFoot(`A session reaches this phone only through its project's node, and only
    by asking: bb phone run --why "…" puts the reason and the command here, in
    front of whoever connected it.`);
  if (!pkgDotsTimer && d.list.querySelector(".dots"))
    pkgDotsTimer = setInterval(pkgTickDots, 400);
  wirePhoneTab(d.el);
}

function wirePhoneTab(root){
  const $$ = id => root.querySelector("#" + id);
  const pick = $$("phPick");
  if (pick) pick.onchange = () => { phNode = pick.value; phIp = ""; phFetch(null, true); };
  const rf = $$("phRefresh");
  if (rf) rf.onclick = () => { phBusy = "asking the node"; phRev++; drawPanes(); phFetch(null, true); };
  // The fields keep what is in them across a redraw.
  const keep = (id, set) => { const el = $$(id); if (el) el.oninput = e => set(e.target.value); };
  keep("phIp", v => phIp = v);
  keep("phPairPort", v => phPort = v);
  keep("phPairCode", v => phCode = v);
  const on = (id, fn) => { const el = $$(id); if (el) el.onclick = fn; };
  on("phConnect", () => {
    if (!phIp.trim()) return notify("the phone's IP, from its wireless debugging screen", true);
    phBusy = "looking for the phone"; phRev++; drawPanes();
    phFetch({action: "connect", ip: phIp.trim()});
  });
  on("phDisconnect", () => { phBusy = "disconnecting"; phRev++; drawPanes();
                             phFetch({action: "disconnect"}); });
  on("phPair", () => {
    phBusy = "pairing"; phRev++; drawPanes();
    phFetch({action: "pair", ip: phIp.trim(), port: phPort.trim(), code: phCode.trim()});
  });
  root.querySelectorAll("[data-allow]").forEach(b => b.onclick = () => {
    phBusy = "running it"; phRev++; drawPanes();
    phFetch({action: "allow", id: Number(b.dataset.allow)});
  });
  root.querySelectorAll("[data-deny]").forEach(b => b.onclick = () =>
    phFetch({action: "deny", id: Number(b.dataset.deny)}));
}
