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
    return;
  }
  const sect = (key, title, status, html, opts = {}) =>
    docSection("network", key, title, status, html.replace(/<h4>[^<]*<\/h4>\s*/, ""), opts);
  const groups = settingsSections().filter(g => NETWORK_GROUPS.includes(g.key));
  const live = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired" && n.live).length;
  d.list.innerHTML = networkReach() + `<div class="sectjump" data-sects></div>`
    + sect("reach", "Reached at", location.protocol.replace(":", ""), `<div class="field" data-group="Reached at"><div class="sub">The page is at ${esc(location.origin)}; a node dials the same address, or the hostname Reach from outside names, and a phone or the companion pins the certificate the Connection group shows.</div></div>`)
    + sect("dial", "Nodes dial in", nodesList === null ? "" : `${live} of ${(nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired").length} answering`, networkDial())
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
