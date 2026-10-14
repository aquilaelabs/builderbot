// The nginx tab (R171, the operator, 10 Oct): one reverse proxy per node,
// BuilderBot's own. One node at a time, picked in the bar like Toolchains
// (the node-switcher rule; the operator, 11 Oct: every tab about settings
// on nodes picks one the same way): a state row saying whether its nginx
// is deployed, the routes (a hostname or path, to a port a container on
// that node publishes, each serving 443 with a pair it picks or the one
// its hostname resolves to, or 80 alone), the certificate pairs the node
// holds (kept on the controller under the domain their names say, pushed
// inside the compose file; a key never comes back; no default, R188), and
// what else on the node holds 80 or 443. Deploy makes the container on a
// node without one; Save writes the routes and certificate and rebuilds a
// deployed one so the change is up; Remove takes it out of the manager.
// The image (R192): what each node's nginx is pinned to, the newest line
// the registry listed (checked weekly, or by Check now), and Update on a
// node that is behind, which pins the new digest and rebuilds.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/nginx, read when the tab opens and after every change; redrawn on
// the nodes revision too, since a node coming or going moves the list.

"use strict";

let nginxList = null;             // last answer, or null before the first
let nginxErr = "";
let nginxRev = 0;
let nginxNode = "";               // the node the tab shows
let nginxLatest = {};             // the registry's newest line, from the same answer
let nginxHostnames = [];          // every node's hostnames: [{name, used: [{node, path, port}]}]
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
    nginxLatest = j.latest || {};
    nginxHostnames = j.hostnames || [];
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
  else if (j.job) notify(`${body.action === "deploy" ? "deploying" : body.action === "update" ? `updating nginx to ${j.to}` : "rebuilding nginx"}${
    body.action === "deploy" ? " nginx" : ""}: its row on the Docker tab has the build`);
  else if (body.action === "check") notify(`the registry lists nginx:${j.latest?.tag || "?"}`);
  // A hostname added or deleted comes back with the list as it now is, so
  // the pull-downs hold it the moment the answer lands rather than after
  // the whole tab is read again (every node's daemon, B721).
  if (Array.isArray(j.hostnames)) nginxHostnames = j.hostnames;
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
// The pair a route serves 443 with (R188): none (80 alone), the one its
// hostname resolves to (its own, else its domain's: `resolved` from the
// server, drawn with the pair's key so the automatic pick is seen), or one
// picked by its key from what the node holds.
function nginxCertPick(n, r){
  const keys = Object.keys(n.certs || {}).filter(k => n.certs[k]?.set).sort();
  const auto = nginxResolve(n, r.host);
  const pick = r.tls === false ? "none" : (keys.includes(r.cert) ? r.cert : "");
  return `<select data-ng="cert" aria-label="the certificate this route serves 443 with">
    <option value="none"${pick === "none" ? " selected" : ""}>80 only</option>
    <option value=""${pick === "" ? " selected" : ""}>443, ${auto ? `${esc(auto)}'s pair` : "no pair covers it yet"}</option>
    ${keys.map(k => `<option value="${esc(k)}"${pick === k ? " selected" : ""}>443, ${esc(k)}'s pair</option>`).join("")}
  </select>`;
}
// What a hostname resolves to with no pick of its own: the server's answer
// for a saved route, and the same rule here for one being typed.
function nginxResolve(n, host){
  if (!host || host === "*") return "";
  if (n.resolved && host in n.resolved) return n.resolved[host];
  const parts = host.split(".");
  for (let i = 0; i < parts.length - 1; i++){
    const cand = parts.slice(i).join(".");
    if (n.certs?.[cand]?.set) return cand;
  }
  return "";
}

// A route's hostname, picked from the one list every node shares (the
// operator, 12 Oct): made once under Hostnames, then any route on any node,
// for any project's container, picks it. Every name (*) beside them.
function nginxHostPick(r){
  const names = nginxHostnames.map(h => h.name);
  if (r.host && r.host !== "*" && !names.includes(r.host)) names.push(r.host);
  // ...and one typed here (the operator, 13 Oct: a subdomain not yet under
  // Hostnames could not be picked): the last choice turns the pick into a
  // box, and Save puts the name on the shared list.
  return `<select data-ng="host" aria-label="hostname">
    ${r.host ? "" : `<option value="" selected>pick a hostname</option>`}
    ${names.map(h => `<option value="${esc(h)}"${h === r.host ? " selected" : ""}>${esc(h)}</option>`).join("")}
    <option value="*"${r.host === "*" ? " selected" : ""}>every name (*)</option>
    <option value="__type">type a hostname…</option>
  </select>`;
}

// The list itself: each name with where it is routed, Delete on one routed
// nowhere, and a box to add one.
function nginxHostLines(){
  const rows = nginxHostnames.map(h => `<div class="nghost"><span class="grow"><code>${esc(h.name)}</code> <span class="dim">${
      h.used.length ? "routed on " + esc([...new Set(h.used.map(u => u.node))].join(", ")) : "not routed yet"}</span></span>${
      h.used.length ? "" : `<button type="button" class="eye rm" data-nghostrm="${esc(h.name)}" aria-label="delete ${esc(h.name)}">${BIN}</button>`}</div>`).join("");
  return `${rows || `<div class="hint">none yet</div>`}
    <div class="actbar"><input data-nghostnew placeholder="www.example.com" aria-label="a hostname to add" autocomplete="off" spellcheck="false">
      <button type="button" data-nghostadd>Add</button></div>`;
}

function nginxRouteRow(n, r, i){
  return `<div class="ngroute" data-i="${i}">
    ${nginxHostPick(r)}
    <input data-ng="path" value="${esc(r.path)}" placeholder="/" aria-label="path" autocomplete="off" spellcheck="false">
    <input data-ng="port" value="${esc(String(r.port))}" placeholder="8080" aria-label="port on the node" inputmode="numeric" autocomplete="off">
    ${nginxCertPick(n, r)}
    <button type="button" class="eye rm" data-ngrm aria-label="remove this route" title="remove this route">${BIN}</button>
  </div>`;
}

// A repaint of the tab: its live key is the revision, so a draft's change
// moves it (drawPanes repaints a tab only when its key has).
function nginxRedraw(){ nginxRev++; drawPanes(); }

function nginxDraftOf(n){
  return nginxDraft[n.node] || (nginxDraft[n.node] = {routes: (n.routes || []).map(r => ({...r})), cert: "", key: "", certFor: ""});
}

// Each pair the node holds, one line (R188): the key it is known by, its
// subject and names, when it ends, and a way to take it off. A pair a
// route picked is said to be in use; taking one off leaves its routes to
// what their hostnames resolve to, or 80 alone.
function nginxCertLines(n, d){
  const own = Object.entries(n.certs || {}).filter(([, c]) => c?.set).sort(([a], [b]) => a.localeCompare(b));
  if (!own.length) return `<div class="hint">none yet: every route answers on 80 only</div>`;
  const routes = d?.routes || n.routes || [];
  return own.map(([k, c]) => {
    const when = c?.expires ? new Date(c.expires * 1000).toLocaleDateString() : "";
    const used = routes.filter(r => r.tls !== false && (r.cert === k || (!r.cert && nginxResolve(n, r.host) === k))).length;
    return `<div class="row ngcert"><div class="grow"><div class="name">${esc(k)}</div>
      <div class="sub">${esc(c.subject || "")}${c.names ? ` (${esc(c.names)})` : ""}${when ? `, until ${esc(when)}` : ""}${
        used ? `; ${used} route${used === 1 ? "" : "s"}` : "; no route"}</div></div>
      <button type="button" class="eye rm" data-ngcertrm="${esc(k)}" aria-label="take ${esc(k)}'s pair off" title="take this pair off the node">${BIN}</button></div>`;
  }).join("");
}

// What the tab says about one node: the state row, the routes, the
// certificates, the clash if any, and the action bar.
// A node without nginx (R181, the operator, 11 Oct): one line saying so and
// Deploy, not the whole form. Routes and certificates come once it is there,
// which is also when they can be tried; a node that already holds routes
// from before says how many Deploy will bring up.
function nginxUndeployed(n){
  const count = (n.routes || []).length, certs = Object.keys(n.certs || {}).length;
  const clash = (n.clash || []).length
    ? `<div class="field"><div class="hint bad">${esc(n.clash.join(", "))} ${n.clash.length === 1 ? "holds" : "hold"} a port nginx needs on this node: it listens on 80 and 443 there, so one of them has to give way.</div></div>` : "";
  return `<div data-ngnode="${esc(n.node)}">
    <div class="row toolstate">
      <div class="grow"><div class="name">nginx on ${esc(n.name)} <span class="pill">not deployed</span></div>
        <div class="sub">${count || certs
          ? `Deploy puts nginx on ${esc(n.name)} with the ${count} route${count === 1 ? "" : "s"} and ${certs} certificate${certs === 1 ? "" : "s"} kept for it`
          : `Deploy puts nginx on ${esc(n.name)}; its routes and certificates are set here once it is there`}</div></div>
    </div>
    ${clash}
    <div class="field"><div class="actbar ngbar" data-ngbar="${esc(n.node)}">
      <span class="state"></span><span class="sp"></span>
      <button type="button" class="primary" data-ngdeploy>Deploy</button>
    </div></div>
  </div>`;
}

function nginxBody(n){
  if (!n.deployed) return nginxUndeployed(n);
  const d = nginxDraftOf(n);
  const count = (n.routes || []).length;
  const pill = n.state?.running === false ? `<span class="pill warn">deployed, down</span>`
    : `<span class="pill ok">deployed</span>`;
  const sub = `nginx-${esc(n.container.replace(/^nginx-/, ""))} on the Docker tab, ${count} route${count === 1 ? "" : "s"}${n.host_only ? "; a hosting-only node" : ""}`;
  // The image it is pinned to, the newest line, and Update when behind
  // (R192): its own action bar, since Check now and Update are two verbs.
  const im = n.image || {}, lt = nginxLatest || {};
  const pinned = `nginx:${im.tag || "?"}${im.digest ? ` (${im.digest.slice(7, 19)})` : ", not pinned to a digest yet"}`;
  const news = n.behind ? `nginx:${n.behind} is out: Update pins it and rebuilds`
    : lt.digest ? "the newest line the registry lists" : "no check has read the registry yet";
  const checked = lt.at ? `checked ${ago(lt.at)}` : "never checked";
  const image = `<div class="field">
      ${lbl("", "Image")}
      <div class="sub ngimage">${esc(pinned)}</div>
      <div class="hint${n.behind ? " warn" : ""}">${esc(news)}. The registry is read once a week by itself; a node is pinned to a digest when it is deployed or updated, so a Save never moves it.</div>
      <div class="actbar ngimgbar"><span class="state">${esc(checked)}${lt.error ? ` · ${esc(lt.error)}` : ""}</span><span class="sp"></span>
        <button type="button" data-ngcheck>Check now</button>
        ${n.behind ? `<button type="button" class="primary" data-ngupdate>Update to ${esc(n.behind)}</button>` : ""}</div>
    </div>`;
  const clash = (n.clash || []).length
    ? `<div class="field"><div class="hint bad">${esc(n.clash.join(", "))} ${n.clash.length === 1 ? "holds" : "hold"} a port nginx needs on this node: it listens on 80 and 443 there, so one of them has to give way.</div></div>` : "";
  return `<div data-ngnode="${esc(n.node)}">
    <div class="row toolstate">
      <div class="grow"><div class="name">nginx on ${esc(n.name)} ${pill}</div>
        <div class="sub">${sub}</div></div>
    </div>
    <div class="field">
      ${lbl("", "Hostnames")}
      <div class="hint">The public names this BuilderBot answers for, on every node's nginx: added once here, picked on any route below. Each points at the node its routes are on (a DNS record, or a tunnel's).</div>
      ${nginxHostLines()}
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
      ${nginxCertLines(n, d)}
      <div class="hint">The pairs this node holds, each known by the domain its names say (a wildcard pair for *.example.com is example.com's; the same again is a renewal). A route serves 443 with the pair it picks, or with its domain's when it picks none; nothing is a default. A key is kept on the controller and never shown.</div>
    </div>
    <div class="field">
      ${lbl("ngCert", "Certificate")}
      <textarea id="ngCert" data-ng="cert" rows="4" spellcheck="false" placeholder="-----BEGIN CERTIFICATE-----">${esc(d.cert)}</textarea>
    </div>
    <div class="field">
      ${lbl("ngKey", "Private key")}
      <textarea id="ngKey" data-ng="key" rows="4" spellcheck="false" placeholder="-----BEGIN PRIVATE KEY-----">${esc(d.key)}</textarea>
    </div>
    <div class="field">
      ${lbl("ngCertFor", "Filed under")}
      <input id="ngCertFor" data-ng="certfor" value="${esc(d.certFor)}" placeholder="from the certificate's names" autocomplete="off" spellcheck="false">
      <div class="hint">Left empty, the pair is filed under the domain its own names say (a wildcard's star taken off), and the routes under that domain find it. Name one only for a pair whose names say no domain (an address, localhost), or to file it under another.</div>
    </div>
    ${image}
    ${clash}
    <div class="field"><div class="actbar ngbar" data-ngbar="${esc(n.node)}">
      <span class="state"></span><span class="sp"></span>
      <button type="button" data-ngsave disabled>Save</button>
      <button type="button" class="caution" data-ngrevert disabled>Revert</button>
      <button type="button" class="danger" data-ngremove>Remove</button>
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
    <span class="sp"></span><button type="button" id="ngReload" title="read the nodes again">Refresh</button>`);
  d.list.innerHTML = n ? nginxBody(n)
    : `<div class="empty">no node to put nginx on yet: enroll one on the Nodes tab</div>`;
  d.setFoot(`One nginx per node, written from here: edit its routes and certificates here, never its file. Deploy and Save build it on the node; its build is on the Docker tab.`);
  wireNginxTab(d.el);
}

// What the node's fields say now, into its draft, and whether that
// differs from what is saved.
function nginxReadDraft(sect, n){
  const d = nginxDraftOf(n);
  d.routes = [...sect.querySelectorAll(".ngroute")].map(row => {
    const pick = row.querySelector('.ngroute [data-ng="cert"]').value;
    return {host: row.querySelector('[data-ng="host"]').value,
            path: row.querySelector('[data-ng="path"]').value.trim() || "/",
            port: row.querySelector('[data-ng="port"]').value.trim(),
            tls: pick !== "none", cert: pick === "none" ? "" : pick};
  });
  d.cert = sect.querySelector('#ngCert').value;
  d.key = sect.querySelector('#ngKey').value;
  d.certFor = sect.querySelector('[data-ng="certfor"]')?.value.trim() || "";
  const shape = r => ({host: r.host, path: r.path, port: String(r.port), tls: r.tls !== false, cert: r.cert || ""});
  const same = JSON.stringify(d.routes.map(shape)) === JSON.stringify((n.routes || []).map(shape));
  return !(same && !d.cert.trim() && !d.key.trim());
}

function wireNginxTab(root){
  const rl = root.querySelector("#ngReload");
  if (rl) rl.onclick = () => { busy(rl, "Refreshing"); loadNginx(); };
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
  // Not deployed: Deploy is the one thing on it (R181).
  if (!n.deployed){
    const dep = bar.querySelector("[data-ngdeploy]");
    if (dep) dep.onclick = async e => {
      busy(e.target, "Deploying");
      await nginxAct({action: "deploy", node: nid});
      nginxRedraw();
    };
    return;
  }
  const sync = e => {
    // "type a hostname…" picked: the pick becomes a box in its place, with
    // the same data-ng, so the draft reads it like any hostname.
    const t = e?.target;
    if (t?.matches?.('select[data-ng="host"]') && t.value === "__type"){
      const box = document.createElement("input");
      box.dataset.ng = "host"; box.placeholder = "app.example.com"; box.autocomplete = "off"; box.spellcheck = false;
      box.setAttribute("aria-label", "hostname");
      t.replaceWith(box); box.focus();
    }
    // The pair a route resolves to follows its hostname: the automatic
    // option said "no pair covers it yet" for a name picked after the
    // row was drawn (the operator, 13 Oct).
    sect.querySelectorAll(".ngroute").forEach(row => {
      const host = row.querySelector('[data-ng="host"]')?.value || "";
      const auto = row.querySelector('[data-ng="cert"] option[value=""]');
      if (auto){ const k = nginxResolve(n, host.trim().toLowerCase()); auto.textContent = `443, ${k ? `${k}'s pair` : "no pair covers it yet"}`; }
    });
    const dirty = nginxReadDraft(sect, n);
    bar.querySelector("[data-ngsave]").disabled = !dirty;
    bar.querySelector("[data-ngrevert]").disabled = !dirty;
  };
  sect.addEventListener("input", sync);
  sect.addEventListener("change", sync);
  // A pair taken off: asked, then saved at once, since what it leaves (a
  // route's pick falling back to its domain's pair, or 80 alone) is drawn
  // from the server's answer.
  sect.querySelectorAll("[data-ngcertrm]").forEach(b => b.onclick = async () => {
    const k = b.dataset.ngcertrm;
    if (!confirm(`Take ${k}'s pair off ${n.name}?\n\nA route that picked it falls back to what its hostname resolves to, or answers on 80 only.`)) return;
    nginxReadDraft(sect, n);
    busy(b, "Removing");
    const j = await nginxAct({action: "save", node: nid, routes: nginxDraftOf(n).routes, drop_cert: k});
    if (!j.error) delete nginxDraft[nid];
    nginxRedraw();
  });
  // The hostname list is saved at the press, and every node's draft kept:
  // it is a list beside the routes, not part of what Save sends.
  const hostAdd = sect.querySelector("[data-nghostadd]"), hostNew = sect.querySelector("[data-nghostnew]");
  if (hostAdd) hostAdd.onclick = async () => {
    const name = hostNew.value.trim();
    if (!name) return;
    nginxReadDraft(sect, n);
    busy(hostAdd, "Adding");
    await nginxAct({action: "host-add", name});
    nginxRedraw();
  };
  if (hostNew) hostNew.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); hostAdd.click(); } };
  sect.querySelectorAll("[data-nghostrm]").forEach(b => b.onclick = async () => {
    nginxReadDraft(sect, n);
    busy(b, "Deleting");
    await nginxAct({action: "host-remove", name: b.dataset.nghostrm});
    nginxRedraw();
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
                              ...(d.cert.trim() ? {cert: d.cert, key: d.key} : {})});
    if (!j.error) delete nginxDraft[nid];
    // Where a pasted pair was filed, since the key is the pair's own to
    // say unless a name was typed.
    if (!j.error && d.cert.trim() && j.host) notify(`${n.name}: the pair is kept as ${j.host}'s`);
    nginxRedraw();
  };
  bar.querySelector("[data-ngrevert]").onclick = () => { delete nginxDraft[nid]; nginxRedraw(); };
  const chk = sect.querySelector("[data-ngcheck]");
  if (chk) chk.onclick = async e => {
    nginxReadDraft(sect, n);
    busy(e.target, "Checking");
    await nginxAct({action: "check", node: nid});
    nginxRedraw();
  };
  const upd = sect.querySelector("[data-ngupdate]");
  if (upd) upd.onclick = async e => {
    if (!confirm(`Update nginx on ${n.name} to nginx:${n.behind}?\n\nIt is rebuilt with the new image, so its sites are down while the node pulls it.`)) return;
    nginxReadDraft(sect, n);
    busy(e.target, "Updating");
    await nginxAct({action: "update", node: nid});
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
