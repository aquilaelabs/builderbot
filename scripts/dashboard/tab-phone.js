// A node's Phone section: a handset on wireless adb, driven from that node.
// It lives on the Nodes tab, under the node it belongs to (the operator,
// 2 Oct: several nodes can each have their own adb and their own phone),
// rather than on a tab of its own with a node picker. Its own classic script
// beside index.html; tab-nodes.js draws the section and calls in here.
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

let ph = null, phBusy = "", phRev = 0, phFetching = false;
let phNode = "";                 // the picked node's id; "" until the first answer
// Held outside the render, because the tab is rebuilt whole on every draw and
// a field that emptied itself mid-sentence would be unusable.
let phIp = "", phPort = "", phCode = "";
// The lend controls' picks, kept across a redraw (R113).
let phLendTo = "", phLendFor = "1";

// The Nodes tab, on the node that holds a phone (or the first that can),
// with its Phone section open: where the phone is now.
function openPhoneTab(){
  const go = () => {
    const n = (ph?.nodes || []).find(x => x.phone) || (ph?.nodes || [])[0];
    if (n){ nodesPick = n.id; phNode = n.id; }
    sectOpen["nodes:phone"] = true;
    openNodesTab();
  };
  if (ph) go(); else phFetch(null, true).then(go);
}

// Connecting, pairing and disconnecting are any account's: a phone is its
// owner's, not the administrators': whoever connects one is the only
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
  // The Nodes tab draws the root asks from the same answer, and the Docker
  // tab the rebuild ones.
  if (tabs.some(t => ["nodes", "docker"].includes(t.kind))) drawPanes();
  drawBell();          // the same asks, in the header
}

// The section's body for one node: its phone, connecting and pairing, the
// lease, the phones it remembers, and what a session waits on. `n` is that
// node's row in the phone answer (ph.nodes).
function phonePanel(n){
  if (!ph) return `<div class="loading">loading…</div>`;
  phNode = n.id;
  const dev = n?.phone;
  const asks = (ph.asks || []).filter(a => a.kind !== "root" && (!a.node || a.node === n.id));
  // This browser's own address wins when it is the phone: viewing the
  // dashboard ON the device is the one case where the number is not something
  // anybody has to go and read. The node's remembered IP is the fallback.
  if (!phIp) phIp = ph.you || n?.ip || "";
  const held = n && n.owner && !n.mine;   // somebody else's connection
  const off = held || !n.live || !mayPhone();
  const offWhy = held ? `connected by ${esc(n.owner.name)}: only they can change it`
    : !n.live ? "the node is not dialing in"
    : "";
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
           ? `${esc(n.name)} is not dialing in; nothing reaches its adb right now`
           : dev ? esc(dev.serial)
           : "try Connect first: a pairing outlives a restart, so it is usually already done"}</div></div>
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
         ? `<div class="sub">this device; you are reading this on it</div>` : ""}
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
            Pair from another device: Android closes the pairing dialog when you leave it.`
         : `On the phone: Wireless debugging, then <b>Pair device with pairing code</b>.
            Keep that dialog open.`}</div>
     </div>`,
  ];
  // Lent to a project (R113): its sessions drive that project's own app on
  // the phone with no ask per command, and the owner watches and takes it
  // back here. The lend controls are the owner's; everybody sees the lease.
  const L = n.lease;
  if (dev && L){
    const left = L.left === null || L.left === undefined ? "until taken back"
      : L.left > 3600 ? `${Math.floor(L.left / 3600)} h ${Math.round((L.left % 3600) / 60)} min left`
      : `${Math.max(1, Math.round(L.left / 60))} min left`;
    rows.push(`<div class="row phlease">
       <div class="grow"><div class="name">Lent to ${esc(L.project)} <span class="pill go">${esc(left)}</span></div>
         <div class="sub">${(L.pkgs || []).length
           ? `its sessions drive ${esc(L.pkgs.join(", "))}, and nothing else, without asking`
           : "its sessions may install one of its builds; then that app, and nothing else, without asking"}</div>${
         L.shot ? `<img class="phshot" alt="the phone's screen, as last seen" src="/api/artifact?project=${
           encodeURIComponent(L.project)}&path=${encodeURIComponent(L.shot)}">
           <div class="sub">${esc(L.shot.split("/").pop())}</div>` : ""}
         ${n.mine ? `<div class="actbar"><span class="state">the screen updates as a session takes shots</span>
           <button type="button" id="phLook">Look now</button>
           <button type="button" class="danger" id="phTakeBack">Take back</button></div>` : ""}</div>
     </div>`);
  } else if (dev && n.mine && mayPhone()){
    const ps = n.lendable || [];
    rows.push(`<div class="row phlend">
       <div class="grow">
         <div class="name">Lend to a project</div>
         <div class="prefrow">
           <label class="pick">Project <select id="phLendTo" aria-label="the project to lend the phone to"${ps.length ? "" : " disabled"}>${
             ps.map(p => `<option value="${esc(p)}"${p === phLendTo ? " selected" : ""}>${esc(p)}</option>`).join("")}</select></label>
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
        <div class="sub">paired or connected here before: Connect is all they need</div>
      </div></div>`,
      ...known.map(k => `<div class="row phknown" data-ip="${esc(k.ip)}">
        <div class="grow">
          <div class="name">${esc(k.model || k.ip)}${
            dev && (dev.serial === k.serial || (dev.model && dev.model === k.model))
              ? ` <span class="pill ok">connected</span>` : ""}</div>
          <div class="sub">${esc(k.ip)}${k.model ? "" : " · paired, never connected from here"} · ${
            esc(ago(k.last || k.first || 0))}${k.by ? ` by ${esc(k.by)}` : ""}</div>
          <div class="actbar">
            <button type="button" data-kconnect="${esc(k.ip)}"${off ? " disabled" : ""} title="${offWhy}">Connect</button>
            <button type="button" class="danger" data-kforget="${esc(k.ip)}">Forget</button>
          </div>
        </div></div>`));
  // What a session is waiting on, above everything else it could be doing:
  // somebody is blocked on it, and that somebody asked YOU: a request only
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
  const L2 = n.lease;
  rows.push(`<div class="actbar phbar"><span class="state">${L2
      ? `Lent to ${esc(L2.project)}: its sessions drive its own app without asking; anything else still asks here.`
      : "A session reaches this phone only by asking; the request lands here, with its reason."}</span>
    <button type="button" id="phRefresh" title="ask the node's adb again now">Refresh</button></div>`);
  if (!tcDotsTimer && rows.join("").includes('class="dots"')) tcDotsTimer = setInterval(tcTickDots, 400);
  return `<div class="phonetab">${rows.join("")}</div>`;
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
  root.querySelectorAll("[data-kconnect]").forEach(b => b.onclick = () => {
    phIp = b.dataset.kconnect;
    phBusy = "looking for the phone"; phRev++; drawPanes();
    phFetch({action: "connect", ip: phIp});
  });
  root.querySelectorAll("[data-kforget]").forEach(b => b.onclick = () =>
    phFetch({action: "forget", ip: b.dataset.kforget}));
  root.querySelectorAll("[data-allow]").forEach(b => b.onclick = () => {
    phBusy = "running it"; phRev++; drawPanes();
    phFetch({action: "allow", id: Number(b.dataset.allow)});
  });
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
