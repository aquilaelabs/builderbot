"use strict";
// The Network page (R165 step 4, the Controller group): how this controller
// is reached, in every edition: the address the page is at and its port,
// what it is served over (the Connection group, with its certificate and
// Let's Encrypt), the addresses the nodes dial in from, and Reach from
// outside (the home tunnel), the last two groups moved here out of
// Controller settings (the operator, 22 Oct). The groups are Settings'
// own builders (tab-settings.js settingsSections), drawn here under this
// page's own list, so a field saves the way it always did. The machine's
// own ports, a bridge, bonds and VLANs are the installed edition's half,
// on This machine's Network section. Chrome from docSurface(); the hard
// rules are uniform.mjs's.

const NETWORK_GROUPS = ["connection", "tunnel"];
const NETWORK_SAYS = {
  reach: "the address, its port, what it is served over",
  dial: "each node, where it dials in from",
  connection: "http, or https with a certificate",
  tunnel: "a hostname that reaches it from outside",
};

function openNetworkTab(){
  openTab({kind: "network", arg: "__network", label: "Network"});
  loadNodes();
}

function networkReach(){
  const t = state?.tls || state?.settings?.tls || {};
  const s = state?.settings?.settings || {};
  const host = s.tls_host?.value || s.tunnel_host?.value || "";
  const served = t.on ? (t.kind === "acme" ? "https, Let's Encrypt" : "https, the install's own certificate") : "http";
  return pageHead({facts: [
    ["Reached at", location.origin],
    ["Port", location.port || (location.protocol === "https:" ? "443" : "80")],
    ["Served over", served],
    ["Hostname", host || "none set"],
    ["Nodes", String((nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired").length)]]});
}

// The dial section's status: how many of the nodes answer.
function networkDialStatus(){
  if (nodesList === null) return "";
  const rows = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  return `${rows.filter(n => n.live).length} of ${rows.length} answering`;
}

function networkDial(){
  const rows = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  if (nodesList === null) return `<div class="field">${skRows(2)}</div>`;
  if (!rows.length) return `<div class="empty">No node yet. Enroll node, on the Nodes page, makes the script that adds a machine; the address it dials is the one this page is reached at, or the hostname Reach from outside names.</div>`;
  const cols = [{label: "Node"}, {label: "Dials in from"}, {label: "Seen"}, {label: "Reaches the controller"}];
  return tblWrap(cols, rows.map(n => `<div class="row">${tblLine(cols, [
    esc(n.name) + (n.config?.own ? ` <span class="tag ndown">this machine</span>` : ""),
    esc(n.agent?.addr || "not yet"),
    n.agent?.last_seen ? esc(ago(n.agent.last_seen)) : "never",
    esc(n.config?.tunnel?.kind === "public" ? `through ${n.config.tunnel.host || "the public hostname"}`
      : n.config?.tunnel?.kind === "wireguard" ? `through WireGuard as ${n.config.tunnel.addr || "?"}` : "on this network")])}</div>`).join(""), "netdial");
}

function renderNetworkInto(i){
  const d = docSurface(i, "network");
  if (!d) return;
  d.setBar("");
  if (!state?.settings){
    d.list.innerHTML = `<div class="row stack2"><div class="grow"><div class="sub">the settings arrive with the first poll…</div></div></div>`;
    delete d.el.dataset.netstamp;
    return;
  }
  // The nodes move with every check-in (nodesRev), and a draw of the whole
  // page on each would replace a secret being typed (a secret is never
  // drafted) and an Apply under the pointer: when only the nodes moved, the
  // head's count and the dial section are written again in place and the
  // settings groups stay as they are.
  const stamp = settingsLive();
  const dial = d.list.querySelector('details[data-sect="network:dial"]');
  if (d.el.dataset.netstamp === stamp && dial){
    // The head replaced whole, never painted inside itself: its markup is
    // a .pghead of its own, and painting it into the old one nested a
    // second box in the first (seen at a desk, 29 Oct).
    const head = d.list.querySelector(":scope > .pghead"), was = head?.dataset.drawn, now = networkReach();
    if (head && was !== now){ head.outerHTML = now; d.list.querySelector(":scope > .pghead")?.setAttribute("data-drawn", now); }
    paint(dial.querySelector(":scope > .body"), networkDial(), true);
    const st = dial.querySelector(":scope > summary .sst"), says = networkDialStatus();
    if (st) st.textContent = says;
    else if (says) dial.querySelector(":scope > summary").insertAdjacentHTML("beforeend", `<span class="sst">${esc(says)}</span>`);
    return;
  }
  d.el.dataset.netstamp = stamp;
  const sect = (key, title, status, html, opts = {}) =>
    docSection("network", key, title, status, html.replace(/<h4>[^<]*<\/h4>\s*/, ""), opts);
  const groups = settingsSections().filter(g => NETWORK_GROUPS.includes(g.key));
  d.list.innerHTML = networkReach() + `<div class="sectjump" data-sects></div>`
    + sect("reach", "Reached at", location.protocol.replace(":", ""), `<div class="field" data-group="Reached at"><div class="sub">The page is at ${esc(location.origin)}; a node dials the same address, or the hostname Reach from outside names, and a phone or the companion pins the certificate the Connection group shows.</div></div>`)
    + sect("dial", "Nodes dial in", networkDialStatus(), networkDial())
    + groups.map(g => sect(g.key, g.title, g.status, withRevert(g.html, g.key), {cls: g.cls})).join("");
  sectJump(d.list.querySelector("[data-sects]"));
  wireSections(d.el);
  splitSects(d.list, "network", {says: NETWORK_SAYS, back: "Network"});
  d.el.querySelectorAll("[data-srevert]").forEach(b => b.onclick = () => {
    const sec = b.closest("details.sect");
    sec?.querySelectorAll("input, select").forEach(i => { if (i.id) delete settingsDraft[i.id]; });
    settingsRev++;
    drawPanes();
  });
  wireSettingsSections(d.el);
  settingsKeep(d.el);
}
