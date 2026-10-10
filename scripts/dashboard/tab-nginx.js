// The nginx tab (R171, the operator, 10 Oct): one reverse proxy per node,
// BuilderBot's own. A section per node: whether its nginx is deployed, the
// routes (a hostname or path, to a port a container on that node
// publishes, with or without TLS), the certificate (kept on the
// controller, pushed inside the compose file; the key never comes back),
// and what else on the node holds 80 or 443. Deploy makes the container on
// a node without one; Save writes the routes and certificate and rebuilds a
// deployed one so the change is up; Remove takes it out of the manager.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/nginx, read when the tab opens and after every change; redrawn on
// the nodes revision too, since a node coming or going moves the sections.

"use strict";

let nginxList = null;             // last answer, or null before the first
let nginxErr = "";
let nginxRev = 0;
// The routes being edited, per node, until Save or Revert; absent while a
// node's section shows what is saved.
const nginxDraft = {};

function openNginxTab(){
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
  return nginxDraft[n.node] || (nginxDraft[n.node] = {routes: (n.routes || []).map(r => ({...r})), cert: "", key: "", drop: false});
}

function nginxSection(n){
  const d = nginxDraftOf(n);
  const cert = n.cert || {};
  const when = cert.expires ? new Date(cert.expires * 1000).toLocaleDateString() : "";
  const status = !n.deployed ? "not deployed"
    : n.state?.running === false ? "deployed, down"
    : `${(n.routes || []).length} route${(n.routes || []).length === 1 ? "" : "s"}`;
  const clash = (n.clash || []).length
    ? `<div class="hint bad">${esc(n.clash.join(", "))} ${n.clash.length === 1 ? "holds" : "hold"} a port nginx needs on this node: it listens on 80 and 443 there, so one of them has to give way.</div>` : "";
  const body = `
    <div class="field">
      <label>Routes</label>
      <div class="hint">Each hostname or path goes to a port a container publishes on ${esc(n.name)}; nginx runs on the host network and reaches it at 127.0.0.1. A name nothing routes is answered by closing the connection.</div>
      <div class="ngroutes">${d.routes.map((r, i) => nginxRouteRow(n, r, i)).join("")}</div>
      <div class="actbar"><span class="state"></span><span class="sp"></span>
        <button type="button" data-ngadd>Add route</button></div>
    </div>
    <div class="field">
      <label>Certificate</label>
      <div class="hint">${cert.set
        ? `Set: ${esc(cert.subject || "")}${cert.names ? ` (${esc(cert.names)})` : ""}${when ? `, until ${esc(when)}` : ""}. Paste a new pair to replace it; the key is kept on the controller and never shown.`
        : "None: routes answer on 80 only. For a site behind Cloudflare, paste a Cloudflare origin certificate and its key."}</div>
      <textarea data-ng="cert" rows="3" spellcheck="false" placeholder="-----BEGIN CERTIFICATE-----">${esc(d.cert)}</textarea>
      <textarea data-ng="key" rows="3" spellcheck="false" placeholder="-----BEGIN PRIVATE KEY-----">${esc(d.key)}</textarea>
      ${cert.set ? `<label class="ndcap"><input type="checkbox" data-ng="drop"${d.drop ? " checked" : ""}> take the certificate off</label>` : ""}
    </div>
    ${clash}
    <div class="field"><div class="actbar ngbar" data-ngbar="${esc(n.node)}">
      <span class="state">${n.deployed ? `nginx-${esc(n.container.replace(/^nginx-/, ""))} on the Docker tab${n.host_only ? "; a hosting-only node" : ""}` : "Save keeps the routes; Deploy puts nginx on the node with them"}</span><span class="sp"></span>
      <button type="button" data-ngsave disabled>Save</button>
      <button type="button" class="caution" data-ngrevert disabled>Revert</button>
      ${n.deployed ? `<button type="button" class="danger" data-ngremove>Remove</button>`
                   : `<button type="button" class="primary" data-ngdeploy>Deploy</button>`}
    </div></div>`;
  return docSection("nginx", n.node, n.name, status, body, {cls: n.clash?.length ? "bad" : ""});
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
  const on = nginxList.filter(n => n.deployed).length;
  d.setBar(`<span class="dim">${nginxList.length} node${nginxList.length === 1 ? "" : "s"}, nginx on ${on}</span>
    <span class="sp"></span><button type="button" id="ngReload" title="read the nodes again">Reload</button>`);
  d.list.innerHTML = nginxList.length
    ? `<div class="sectjump" data-sects></div>` + nginxList.map(nginxSection).join("")
    : `<div class="empty">no node to put nginx on yet: enroll one on the Nodes tab</div>`;
  d.setFoot(`One nginx per node, written from here: edit its routes and certificate here, never its file. Deploy and Save build it on the node; its build is on the Docker tab.`);
  wireNginxTab(d.el);
}

// What one section's fields say now, into its draft, and whether that
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
  const same = JSON.stringify(d.routes.map(r => ({...r, port: String(r.port)})))
    === JSON.stringify((n.routes || []).map(r => ({host: r.host, path: r.path, port: String(r.port), tls: r.tls !== false})));
  return !(same && !d.cert.trim() && !d.key.trim() && !d.drop);
}

function wireNginxTab(root){
  const rl = root.querySelector("#ngReload");
  if (rl) rl.onclick = () => { busy(rl, "Reading"); loadNginx(); };
  if (root.querySelector("[data-sects]")) sectJump(root.querySelector("[data-sects]"));
  wireSections(root);
  root.querySelectorAll("details.sect[data-sect^='nginx:']").forEach(sect => {
    const nid = sect.dataset.sect.slice("nginx:".length);
    const n = nginxList.find(x => x.node === nid);
    if (!n) return;
    const bar = sect.querySelector(".ngbar");
    const sync = () => {
      const dirty = nginxReadDraft(sect, n);
      bar.querySelector("[data-ngsave]").disabled = !dirty;
      bar.querySelector("[data-ngrevert]").disabled = !dirty;
    };
    sect.addEventListener("input", sync);
    sect.addEventListener("change", sync);
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
      const j = await nginxAct({action: "save", node: nid, routes: d.routes,
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
  });
}
