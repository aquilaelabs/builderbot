// The nginx tab (R171, the operator, 10 Oct): one reverse proxy per node,
// BuilderBot's own. One node at a time, picked in the bar like Toolchains
// (the node-switcher rule; the operator, 11 Oct: every tab about settings
// on nodes picks one the same way): a state row saying whether its nginx
// is deployed, the routes (a hostname or path, to a port a container on
// that node publishes, with or without TLS), the certificates (kept on the
// controller, pushed inside the compose file; a key never comes back), and
// what else on the node holds 80 or 443. Deploy makes the container on a
// node without one; Save writes the routes and certificate and rebuilds a
// deployed one so the change is up; Remove takes it out of the manager.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/nginx, read when the tab opens and after every change; redrawn on
// the nodes revision too, since a node coming or going moves the list.

"use strict";

let nginxList = null;             // last answer, or null before the first
let nginxErr = "";
let nginxRev = 0;
let nginxNode = "";               // the node the tab shows
// The routes being edited, per node, until Save or Revert; absent while a
// node shows what is saved.
const nginxDraft = {};

function openNginxTab(node){
  if (node) nginxNode = node;
  openTab({kind: "nginx", arg: "__nginx", label: "nginx"});
}

async function loadNginx(){
  try{
    const j = await (await fetch("/api/nginx")).json();
    nginxErr = j.error || "";
    nginxList = j.nodes || [];
  }catch(e){
    nginxErr = String(e);
    nginxList = nginxList || [];
  }
  nginxRev++;
  if (tabs.some(t => t.kind === "nginx")) drawPanes();
}

async function nginxAct(body){
  const j = await (await postJSON("/api/nginx", body)).json().catch(() => ({error: "no answer"}));
  if (j.error) notify(j.error, true);
  else if (j.note) notify(j.note, true);
  else if (j.job) notify(`${body.action === "deploy" ? "deploying" : "rebuilding"} nginx: its row on the Docker tab has the build`);
  await loadNginx();
  return j;
}

// The node the tab opens on: the one it showed last (remembered in this
// browser), else the first in the answer, else nothing. Re-asked on every
// draw, so a node retired under the tab is not shown as if it were there.
function nginxPick(){
  const have = nginxList || [];
  let want = nginxNode;
  if (!have.some(n => n.node === want)){
    try{ want = localStorage.getItem("bb.ngnode") || ""; }catch(e){ want = ""; }
  }
  if (!have.some(n => n.node === want)) want = have[0]?.node || "";
  nginxNode = want;
  return have.find(n => n.node === want) || null;
}

// A route as a row of fields: hostname, path, port, TLS, and Remove.
function nginxRouteRow(n, r, i){
  return `<div class="ngroute" data-i="${i}">
    <input data-ng="host" value="${esc(r.host)}" placeholder="www.example.com or *" aria-label="hostname" autocomplete="off" spellcheck="false">
    <input data-ng="path" value="${esc(r.path)}" placeholder="/" aria-label="path" autocomplete="off" spellcheck="false">
    <input data-ng="port" value="${esc(String(r.port))}" placeholder="8080" aria-label="port on the node" inputmode="numeric" autocomplete="off">
    <label class="ndcap"><input type="checkbox" data-ng="tls"${r.tls !== false ? " checked" : ""}> 443 too</label>
    <button type="button" class="eye rm" data-ngrm aria-label="remove this route" title="remove this route">${BIN}</button>
  </div>`;
}

// A repaint of the tab: its live key is the revision, so a draft's change
// moves it (drawPanes repaints a tab only when its key has).
function nginxRedraw(){ nginxRev++; drawPanes(); }

function nginxDraftOf(n){
  return nginxDraft[n.node] || (nginxDraft[n.node] = {routes: (n.routes || []).map(r => ({...r})), cert: "", key: "", drop: false, certFor: ""});
}

// The hostnames a certificate can be for: the routes' own, without *.
function nginxHosts(n, d){
  return [...new Set([...(d?.routes || n.routes || []).map(r => r.host), ...Object.keys(n.certs || {})])]
    .filter(h => h && h !== "*").sort();
}

// Each certificate the node holds, one line: the default, then each
// hostname's own, with its name and when it ends.
function nginxCertLines(n){
  const line = (label, c) => {
    const when = c?.expires ? new Date(c.expires * 1000).toLocaleDateString() : "";
    return `${esc(label)}: ${c?.set ? `${esc(c.subject || "")}${c.names ? ` (${esc(c.names)})` : ""}${when ? `, until ${esc(when)}` : ""}` : "none"}`;
  };
  const own = Object.entries(n.certs || {}).filter(([, c]) => c?.set).sort(([a], [b]) => a.localeCompare(b));
  return [line("Default", n.cert), ...own.map(([h, c]) => line(h, c))].join("<br>")
    + (!n.cert?.set && !own.length ? " (routes answer on 80 only)" : "");
}

// What the tab says about one node: the state row, the routes, the
// certificates, the clash if any, and the action bar.
function nginxBody(n){
  const d = nginxDraftOf(n);
  const cert = n.cert || {};
  const count = (n.routes || []).length;
  const pill = !n.deployed ? `<span class="pill">not deployed</span>`
    : n.state?.running === false ? `<span class="pill warn">deployed, down</span>`
    : `<span class="pill ok">deployed</span>`;
  const sub = n.deployed
    ? `nginx-${esc(n.container.replace(/^nginx-/, ""))} on the Docker tab, ${count} route${count === 1 ? "" : "s"}${n.host_only ? "; a hosting-only node" : ""}`
    : "Save keeps the routes; Deploy puts nginx on the node with them";
  const clash = (n.clash || []).length
    ? `<div class="field"><div class="hint bad">${esc(n.clash.join(", "))} ${n.clash.length === 1 ? "holds" : "hold"} a port nginx needs on this node: it listens on 80 and 443 there, so one of them has to give way.</div></div>` : "";
  return `<div data-ngnode="${esc(n.node)}">
    <div class="row toolstate">
      <div class="grow"><div class="name">nginx on ${esc(n.name)} ${pill}</div>
        <div class="sub">${sub}</div></div>
    </div>
    <div class="field">
      ${lbl("", "Routes")}
      <div class="hint">Each hostname or path goes to a port a container publishes on ${esc(n.name)}; nginx runs on the host network and reaches it at 127.0.0.1. A name nothing routes is answered by closing the connection.</div>
      <div class="ngroutes">${d.routes.map((r, i) => nginxRouteRow(n, r, i)).join("")}</div>
      <div class="actbar"><span class="state">${count ? "" : "no route yet"}</span><span class="sp"></span>
        <button type="button" data-ngadd>Add route</button></div>
    </div>
    <div class="field">
      ${lbl("", "Certificates")}
      <div class="hint">${nginxCertLines(n)}</div>
      <div class="hint">One per hostname where a site needs its own (an origin certificate covers one domain), and the node's default for every hostname without one. Paste a pair for the one picked; a key is kept on the controller and never shown.</div>
    </div>
    <div class="field">
      ${lbl("ngCertFor", "For")}
      <select id="ngCertFor" data-ng="certfor" aria-label="which hostname the pasted certificate is for">
        <option value=""${!d.certFor ? " selected" : ""}>the node's default (any hostname without its own)</option>
        ${nginxHosts(n, d).map(h => `<option value="${esc(h)}"${d.certFor === h ? " selected" : ""}>${esc(h)}</option>`).join("")}
      </select>
    </div>
    <div class="field">
      ${lbl("ngCert", "Certificate")}
      <textarea id="ngCert" data-ng="cert" rows="4" spellcheck="false" placeholder="-----BEGIN CERTIFICATE-----">${esc(d.cert)}</textarea>
    </div>
    <div class="field">
      ${lbl("ngKey", "Private key")}
      <textarea id="ngKey" data-ng="key" rows="4" spellcheck="false" placeholder="-----BEGIN PRIVATE KEY-----">${esc(d.key)}</textarea>
      ${(d.certFor ? n.certs?.[d.certFor]?.set : cert.set) ? `<label class="ndcap"><input type="checkbox" data-ng="drop"${d.drop ? " checked" : ""}> take ${d.certFor ? esc(d.certFor) + "'s" : "the default"} certificate off</label>` : ""}
    </div>
    ${clash}
    <div class="field"><div class="actbar ngbar" data-ngbar="${esc(n.node)}">
      <span class="state"></span><span class="sp"></span>
      <button type="button" data-ngsave disabled>Save</button>
      <button type="button" class="caution" data-ngrevert disabled>Revert</button>
      ${n.deployed ? `<button type="button" class="danger" data-ngremove>Remove</button>`
                   : `<button type="button" class="primary" data-ngdeploy>Deploy</button>`}
    </div></div>
  </div>`;
}

function renderNginxInto(i){
  const d = docSurface(i, "nginx");
  if (!d) return;
  if (nginxList === null){
    d.list.innerHTML = `<div class="loading">loading…</div>`;
    loadNginx();
    return;
  }
  if (nginxErr){
    d.list.innerHTML = `<div class="hint bad">${esc(nginxErr)}</div>`;
    return;
  }
  const n = nginxPick();
  const pnodes = nginxList.map(x => ({id: x.node, name: x.name, live: x.live}));
  d.setBar(`${nodePick("ngNodeSel", pnodes, nginxNode)}
    <span class="sp"></span><button type="button" id="ngReload" title="read the nodes again">Reload</button>`);
  d.list.innerHTML = n ? nginxBody(n)
    : `<div class="empty">no node to put nginx on yet: enroll one on the Nodes tab</div>`;
  d.setFoot(`One nginx per node, written from here: edit its routes and certificates here, never its file. Deploy and Save build it on the node; its build is on the Docker tab.`);
  wireNginxTab(d.el);
}

// What the node's fields say now, into its draft, and whether that
// differs from what is saved.
function nginxReadDraft(sect, n){
  const d = nginxDraftOf(n);
  d.routes = [...sect.querySelectorAll(".ngroute")].map(row => ({
    host: row.querySelector('[data-ng="host"]').value.trim(),
    path: row.querySelector('[data-ng="path"]').value.trim() || "/",
    port: row.querySelector('[data-ng="port"]').value.trim(),
    tls: row.querySelector('[data-ng="tls"]').checked}));
  d.cert = sect.querySelector('[data-ng="cert"]').value;
  d.key = sect.querySelector('[data-ng="key"]').value;
  d.drop = !!sect.querySelector('[data-ng="drop"]')?.checked;
  d.certFor = sect.querySelector('[data-ng="certfor"]')?.value || "";
  const same = JSON.stringify(d.routes.map(r => ({...r, port: String(r.port)})))
    === JSON.stringify((n.routes || []).map(r => ({host: r.host, path: r.path, port: String(r.port), tls: r.tls !== false})));
  return !(same && !d.cert.trim() && !d.key.trim() && !d.drop);
}

function wireNginxTab(root){
  const rl = root.querySelector("#ngReload");
  if (rl) rl.onclick = () => { busy(rl, "Reading"); loadNginx(); };
  const psel = root.querySelector("#ngNodeSel");
  if (psel) psel.onchange = () => { nginxNode = psel.value;
                                    try{ localStorage.setItem("bb.ngnode", nginxNode); }catch(e){ /* private */ }
                                    nginxRedraw(); };
  const sect = root.querySelector("[data-ngnode]");
  if (!sect) return;
  const nid = sect.dataset.ngnode;
  const n = nginxList.find(x => x.node === nid);
  if (!n) return;
  const bar = sect.querySelector(".ngbar");
  const sync = () => {
    const dirty = nginxReadDraft(sect, n);
    bar.querySelector("[data-ngsave]").disabled = !dirty;
    bar.querySelector("[data-ngrevert]").disabled = !dirty;
  };
  sect.addEventListener("input", sync);
  sect.addEventListener("change", e => {
    if (e.target.matches?.('[data-ng="certfor"]')){ nginxReadDraft(sect, n); nginxRedraw(); return; }
    sync();
  });
  sect.querySelector("[data-ngadd]").onclick = () => {
    nginxReadDraft(sect, n);
    nginxDraftOf(n).routes.push({host: "", path: "/", port: "", tls: true});
    nginxRedraw();
  };
  sect.querySelectorAll("[data-ngrm]").forEach(b => b.onclick = () => {
    nginxReadDraft(sect, n);
    nginxDraftOf(n).routes.splice(+b.closest(".ngroute").dataset.i, 1);
    nginxRedraw();
  });
  bar.querySelector("[data-ngsave]").onclick = async e => {
    nginxReadDraft(sect, n);
    const d = nginxDraftOf(n);
    busy(e.target, "Saving");
    const j = await nginxAct({action: "save", node: nid, routes: d.routes, cert_for: d.certFor,
                              ...(d.cert.trim() ? {cert: d.cert, key: d.key} : {}), drop_cert: d.drop});
    if (!j.error) delete nginxDraft[nid];
    nginxRedraw();
  };
  bar.querySelector("[data-ngrevert]").onclick = () => { delete nginxDraft[nid]; nginxRedraw(); };
  const dep = bar.querySelector("[data-ngdeploy]");
  if (dep) dep.onclick = async e => {
    if (nginxReadDraft(sect, n) && !confirm(`Deploy nginx on ${n.name} with what is saved? Unsaved changes here are not in it: Save first to include them.`)) return;
    busy(e.target, "Deploying");
    await nginxAct({action: "deploy", node: nid});
    nginxRedraw();
  };
  const rm = bar.querySelector("[data-ngremove]");
  if (rm) rm.onclick = async e => {
    if (!confirm(`Remove nginx from ${n.name}?\n\nThe container comes down and leaves the Docker tab; the routes and certificate stay here for a redeploy.`)) return;
    busy(e.target, "Removing");
    await nginxAct({action: "remove", node: nid});
    nginxRedraw();
  };
  sync();
}
