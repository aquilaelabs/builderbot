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
let nginxCertOpen = false;        // Add a certificate pressed: its form unrolled
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
    const j = await (await bootFetch("/api/nginx")).json();
    nginxErr = j.error || "";
    nginxList = j.nodes || [];
    nginxLatest = j.latest || {};
    nginxHostnames = j.hostnames || [];
  }catch(e){
    nginxErr = String(e);
    nginxList = nginxList || [];
  }
  nginxRev++;
  if (tabs.some(t => t.kind === "nginx")){ const f = nginxKeepTyping(); drawPanes(); nginxRefocus(f); }
}

// What is being typed survives a re-read (B729): the rows are read into the
// node's draft before the poll's redraw, and the field with focus gets it
// back with its caret, so a hostname half typed is not swapped for the
// pulldown it was typed in place of.
function nginxKeepTyping(){
  const sect = document.querySelector(".nginxtab [data-ngnode]");
  const n = sect && (nginxList || []).find(x => x.node === sect.dataset.ngnode);
  if (!n || !sect.querySelector("#ngCert")) return null;    // undeployed: no rows to read
  nginxReadDraft(sect, n);
  const a = document.activeElement, row = a?.closest?.(".ngroute");
  return row && a.dataset.ng ? {i: row.dataset.i, k: a.dataset.ng, pos: a.selectionStart} : null;
}
function nginxRefocus(f){
  const el = f && document.querySelector(`.nginxtab .ngroute[data-i="${f.i}"] [data-ng="${f.k}"]`);
  if (!el) return;
  el.focus();
  if (typeof f.pos === "number"){ try{ el.setSelectionRange(f.pos, f.pos); }catch(e){ /* a select */ } }
}

async function nginxAct(body){
  const j = await (await postJSON("/api/nginx", body)).json().catch(() => ({error: "no answer"}));
  if (j.error) notify(j.error, true);
  else if (j.note) notify(j.note, true);
  else if (j.job) notify(`${body.action === "deploy" ? "deploying" : body.action === "update" ? `updating nginx to ${j.to}` : "rebuilding nginx"}${
    body.action === "deploy" ? " nginx" : ""}: its row on the Containers page has the build`);
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
    ${optionList([["none", "80 only"], ["", `443, ${auto ? `${auto}'s pair` : "no pair covers it yet"}`],
                  ...keys.map(k => [k, `443, ${k}'s pair`])], pick)}
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
  // box, and Save puts the name on the shared list. A row typed into is
  // drawn as the box again (B729): the draft remembers, so a redraw from
  // the poll does not hand the pulldown back mid-word.
  if (r.typed) return `<input data-ng="host" value="${esc(r.host || "")}" placeholder="app.example.com" aria-label="hostname" autocomplete="off" spellcheck="false">`;
  return `<select data-ng="host" aria-label="hostname">
    ${r.host ? "" : `<option value="" selected>pick a hostname</option>`}
    ${optionList(names, r.host)}
    <option value="*"${r.host === "*" ? " selected" : ""}>every name (*)</option>
    <option value="__type">type a hostname…</option>
  </select>`;
}

// The list itself: each name with where it is routed, Delete on one routed
// nowhere, and a box to add one.
function nginxHostLines(){
  const rows = nginxHostnames.map(h => `<div class="nghost"><span class="grow"><code>${esc(h.name)}</code> <span class="dim">${
      h.used.length ? "routed on " + esc([...new Set(h.used.map(u => u.node))].join(", ")) : "not routed yet"}</span></span>${
      h.used.length ? "" : rmIcon(`data-nghostrm="${esc(h.name)}"`, `delete ${h.name}`)}</div>`).join("");
  return `${rows || `<div class="hint">none yet</div>`}
    <div class="actbar"><input data-nghostnew placeholder="www.example.com" aria-label="a hostname to add" autocomplete="off" spellcheck="false">
      <button type="button" data-nghostadd>Add</button></div>`;
}

// Routes as records (R218 step 44, the design's record-lists rule, the
// operator 19 Oct: lists like Cloudflare's DNS page): a table, a row a route
// read-only with Edit at its right; Edit opens that row in place into its
// form (Delete, Cancel, Save), Add route opens the same form at the table's
// top, one open at a time, and Save writes that one route.
const NG_ROUTE_COLS = [{label: "Hostname"}, {label: "Path", w: "minmax(0,.6fr)"}, {label: "Port", w: "5rem", num: true},
  {label: "TLS"}, {act: true, w: "5rem"}];
let nginxEdit = null;            // {node, i}: the route open in its form, i -1 for a new one
let nginxForm = null;            // that form's fields as typed, kept across a poll's redraw
function nginxTls(n, r){
  if (r.tls === false) return "80 only";
  if (r.cert) return `443, ${esc(r.cert)}'s pair`;
  const auto = nginxResolve(n, r.host);
  return auto ? `443, ${esc(auto)}'s pair` : `<span class="warn">443, no pair covers it yet</span>`;
}
function nginxRouteForm(n, r, i){
  return `<div class="ngform ngroute" data-i="${i}">
    <div class="ngfields">
      <label class="setrow col ctlrow"><span class="lbl">Hostname</span>${nginxHostPick(r)}</label>
      <label class="setrow col ctlrow"><span class="lbl">Path</span><input data-ng="path" value="${esc(r.path || "/")}" placeholder="/" aria-label="path" autocomplete="off" spellcheck="false"></label>
      <label class="setrow col ctlrow"><span class="lbl">Port</span><input data-ng="port" value="${esc(String(r.port ?? ""))}" placeholder="8080" aria-label="port on the node" inputmode="numeric" autocomplete="off"></label>
      <label class="setrow col ctlrow"><span class="lbl">TLS</span>${nginxCertPick(n, r)}</label>
    </div>
    <div class="actbar ngformbar">${i >= 0 ? `<button type="button" class="danger lead" data-ngdel>Delete</button>` : ""}
      <button type="button" data-ngcancel>Cancel</button>
      <button type="button" class="primary" data-ngsave>Save</button></div>
  </div>`;
}
function nginxRoutesTable(n){
  const ed = nginxEdit && nginxEdit.node === n.node ? nginxEdit.i : null;
  const rec = (r, i) => `<div class="row ngrec${ed === i ? " open" : ""}" data-i="${i}">${tblLine(NG_ROUTE_COLS, [
      r.host === "*" ? "every name (*)" : esc(r.host || ""), esc(r.path || "/"), esc(String(r.port)), nginxTls(n, r),
      ed === i ? "" : `<button type="button" data-ngedit="${i}">Edit</button>`])}${
      ed === i ? nginxRouteForm(n, nginxForm || r, i) : ""}</div>`;
  const fresh = ed === -1 ? `<div class="row ngrec open" data-i="-1">${nginxRouteForm(n, nginxForm || {host: "", path: "/", port: "", tls: true}, -1)}</div>` : "";
  const routes = n.routes || [];
  if (!routes.length && ed !== -1) return `<div class="hint">no route yet: Add route sends a hostname to a port a container publishes</div>`;
  return tblWrap(NG_ROUTE_COLS, fresh + routes.map(rec).join(""), "ngrecords");
}

// A repaint of the tab: its live key is the revision, so a draft's change
// moves it (drawPanes repaints a tab only when its key has).
function nginxRedraw(){ nginxRev++; drawPanes(); }

// Routes are filled from the node when they are not drafted (null), so
// Routes' Save and Revert can let go of the routes and keep a pair half
// pasted under Certificates, and Add the other way about.
function nginxDraftOf(n){
  const d = nginxDraft[n.node] || (nginxDraft[n.node] = {routes: null, cert: "", key: "", certFor: ""});

  return d;
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
      ${rmIcon(`data-ngcertrm="${esc(k)}"`, `take ${k}'s pair off`, {title: "take this pair off the node"})}</div>`;
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
  // The page's status line (the operator, 17 Oct: one order for every
  // page's top): not deployed and what Deploy brings; Deploy is in the bar
  // with every header button.
  return `<div data-ngnode="${esc(n.node)}">
    ${headLine(`<span class="pill">not deployed</span> ${count || certs
          ? `Deploy puts nginx on ${esc(n.name)} with the ${count} route${count === 1 ? "" : "s"} and ${certs} certificate${certs === 1 ? "" : "s"} kept for it`
          : `Deploy puts nginx on ${esc(n.name)}; its routes and certificates are set here once it is there`}`, "", "toolstate")}
    ${clash}
  </div>`;
}

// The page's four sections, named once for the page and its placeholder
// alike (R218, the operator 18 Oct: the nginx placeholder was a few gray
// lines while every other page's waited as itself).
const NG_TITLES = {hostnames: "Hostnames", routes: "Routes", certs: "Certificates", image: "Image"};
function ngSect(key, status, body, opts){ return docSection("nginx", key, NG_TITLES[key], status, body, opts); }

function nginxBody(n){
  if (!n.deployed) return nginxUndeployed(n);
  const d = nginxDraftOf(n);
  const count = (n.routes || []).length;
  const pill = n.state?.running === false ? `<span class="pill warn">deployed, down</span>`
    : `<span class="pill ok">deployed</span>`;
  const sub = `nginx-${esc(n.container.replace(/^nginx-/, ""))} on the ${pageLink("docker", "Containers page")}, ${count} route${count === 1 ? "" : "s"}${n.host_only ? "; a hosting-only node" : ""}`;
  // The image it is pinned to, the newest line, and Update when behind
  // (R192): its own action bar, since Check now and Update are two verbs.
  const im = n.image || {}, lt = nginxLatest || {};
  const pinned = `nginx:${im.tag || "?"}${im.digest ? ` (${im.digest.slice(7, 19)})` : ", not pinned to a digest yet"}`;
  const news = n.behind ? `nginx:${n.behind} is out: Update pins it and rebuilds`
    : lt.digest ? "the newest line the registry lists" : "no check has read the registry yet";
  const checked = lt.at ? `checked ${ago(lt.at)}` : "never checked";
  // Four sections (R218 step 29): each says its state in its head, opens
  // on one short line with the rest behind its ?, and saves what it writes
  // under itself; Remove stands apart at the page's foot.
  const pairs = Object.values(n.certs || {}).filter(c => c?.set).length;
  const image = ngSect("image", n.behind ? `nginx:${n.behind} is out` : `nginx:${im.tag || "?"}`,
    `<div class="field">
      <div class="sub ngimage">${esc(pinned)}</div>
      <div class="hint${n.behind ? " warn" : ""}">${esc(news)}.${helpIcon("The registry is read once a week by itself; a node is pinned to a digest when it is deployed or updated, so a Save never moves it.")}</div>
      <div class="actbar ngimgbar"><span class="state">${esc(checked)}${lt.error ? ` · ${esc(lt.error)}` : ""}</span><span class="sp"></span>
        <button type="button" data-ngcheck>Check now</button>
        ${n.behind ? `<button type="button" class="primary" data-ngupdate>Update to ${esc(n.behind)}</button>` : ""}</div>
    </div>`, {cls: n.behind ? "warn" : ""});
  const clash = (n.clash || []).length
    ? `<div class="field"><div class="hint bad">${esc(n.clash.join(", "))} ${n.clash.length === 1 ? "holds" : "hold"} a port nginx needs on this node: it listens on 80 and 443 there, so one of them has to give way.</div></div>` : "";
  const hostN = (nginxHostnames || []).length;
  const hosts = ngSect("hostnames", hostN ? `${hostN} name${hostN === 1 ? "" : "s"}` : "none yet",
    `<div class="field"><div class="hint">The names this BuilderBot answers for, picked on any route.${helpIcon(
      "The public names this BuilderBot answers for, on every node's nginx: added once here, picked on any route below. Each points at the node its routes are on (a DNS record, or a tunnel's). Added and deleted at the press.")}</div>
      ${nginxHostLines()}</div>`);
  const routes = ngSect("routes", count ? `${count} route${count === 1 ? "" : "s"}` : "no route yet",
    `<div class="field"><div class="hint">Each hostname or path to a port a container publishes on ${esc(n.name)}.${helpIcon(
      "nginx runs on the host network and reaches a container at 127.0.0.1. A route serves 443 with the pair it picks, or with its domain's when it picks none; nothing is a default. A name nothing routes is answered by closing the connection.")}</div></div>
      <div class="field"><div class="addbar ctlrow" data-add="route"><button type="button" data-ngadd${nginxEdit?.node === n.node && nginxEdit.i === -1 ? " disabled" : ""}>Add route</button></div></div>
      <div class="field ngroutes">${nginxRoutesTable(n)}</div>`);
  // The pairs held, and Add a certificate unrolling the form under them: a
  // paste is now and then, not on every visit (the operator, step 29).
  const open = nginxCertOpen || !!(d.cert.trim() || d.key.trim());
  const certs = ngSect("certs", pairs ? `${pairs} pair${pairs === 1 ? "" : "s"}` : "none yet",
    `<div class="field"><div class="hint">The pairs this node holds, each known by its domain.${helpIcon(
      "A pair is known by the domain its names say: a wildcard pair for *.example.com is example.com's, and the same again is a renewal. A key is kept on the controller and never shown.")}</div>
      ${nginxCertLines(n, d)}</div>
    <div class="field ngcertadd"${open ? " hidden" : ""}><div class="actbar"><span class="sp"></span>
      <button type="button" data-ngcertopen>Add a certificate</button></div></div>
    <div class="ngcertform"${open ? "" : " hidden"}>
      <div class="field">
        ${lbl("ngCert", "Certificate")}
        <textarea id="ngCert" data-ng="cert" rows="4" spellcheck="false" placeholder="-----BEGIN CERTIFICATE-----">${esc(d.cert)}</textarea>
      </div>
      <div class="field">
        ${lbl("ngKey", "Private key")}
        <textarea id="ngKey" data-ng="key" rows="4" spellcheck="false" placeholder="-----BEGIN PRIVATE KEY-----">${esc(d.key)}</textarea>
      </div>
      <div class="field">
        ${lbl("ngCertFor", "Filed under", "Left empty, the pair is filed under the domain its own names say (a wildcard's star taken off), and the routes under that domain find it. Name one only for a pair whose names say no domain (an address, localhost), or to file it under another.")}
        <input id="ngCertFor" data-ng="certfor" value="${esc(d.certFor)}" placeholder="from the certificate's names" autocomplete="off" spellcheck="false">
      </div>
      <div class="field"><div class="actbar ngcertbar"><span class="state"></span><span class="sp"></span>
        <button type="button" class="primary" data-ngcertsave disabled>Add</button>
        <button type="button" data-ngcertcancel>Cancel</button></div></div>
    </div>`);
  // The page's status line, deployed as undeployed (the page tops' one
  // order): its state and what it runs, under the tiles.
  return `<div data-ngnode="${esc(n.node)}">
    ${headLine(`${pill} <span class="sub">${sub}</span>`, "", "toolstate")}
    ${clash}
    ${hosts}
    ${routes}
    ${certs}
    ${image}
    <div class="field"><div class="actbar ngfoot"><span class="sp"></span>
      <button type="button" class="danger" data-ngremove>Remove nginx</button></div></div>
  </div>`;
}

// The bar, the page's and its placeholder's (R218, the operator 18 Oct):
// the node switcher, and Deploy, an undeployed node's one action, at its
// right; waiting, which node and whether it is deployed are not known yet.
function nginxBar(pnodes, n){
  return nodeBar(nodePick("ngNodeSel", pnodes, nginxNode),
                 n && !n.deployed ? `<button type="button" class="primary" data-ngdeploy>Deploy</button>` : "");
}

function renderNginxInto(i){
  const d = docSurface(i, "nginx");
  if (!d) return;
  if (nginxList === null){
    // Its template (R218 step 16): the bar and the state row's words are
    // the page's own; the node and its routes are on their way.
    d.setBar(nginxBar(null));
    d.list.innerHTML = skTpl(`${headLine(`${skv(5)} ${skv(24)}`, "", "toolstate")}${
      ["hostnames", "routes", "certs", "image"].map(k => ngSect(k, "", `<div class="field">${skRows(2)}</div>`)).join("")}`);
    loadNginx();
    return;
  }
  if (nginxErr){
    d.list.innerHTML = `<div class="hint bad">${esc(nginxErr)}</div>`;
    return;
  }
  const n = nginxPick();
  const pnodes = nginxList.map(x => ({id: x.node, name: x.name, live: x.live}));
  d.setBar(nginxBar(pnodes, n));
  d.list.innerHTML = n ? nginxBody(n)
    : noNodeYet("nginx runs on a node");
  wireNginxTab(d.el);
}

// The open route's form as typed, into nginxForm, and a pair half pasted
// under Certificates, into the node's draft: both kept across a redraw.
function nginxReadDraft(sect, n){
  const d = nginxDraftOf(n), f = sect.querySelector(".ngform");
  if (f){
    const pick = f.querySelector('[data-ng="cert"]').value, host = f.querySelector('[data-ng="host"]');
    nginxForm = {host: host.value === "__type" ? "" : host.value, typed: host.tagName === "INPUT",
                 path: f.querySelector('[data-ng="path"]').value.trim() || "/",
                 port: f.querySelector('[data-ng="port"]').value.trim(),
                 tls: pick !== "none", cert: pick === "none" ? "" : pick};
  }
  d.cert = sect.querySelector('#ngCert')?.value || "";
  d.key = sect.querySelector('#ngKey')?.value || "";
  d.certFor = sect.querySelector('[data-ng="certfor"]')?.value.trim() || "";
}

function wireNginxTab(root){
  const psel = root.querySelector("#ngNodeSel");
  if (psel) psel.onchange = () => { nginxNode = psel.value;
                                    try{ localStorage.setItem("bb.ngnode", nginxNode); }catch(e){ /* private */ }
                                    nginxRedraw(); };
  const sect = root.querySelector("[data-ngnode]");
  if (!sect) return;
  const nid = sect.dataset.ngnode;
  const n = nginxList.find(x => x.node === nid);
  if (!n) return;
  // Not deployed: Deploy is the one thing on it (R181).
  if (!n.deployed){
    const dep = root.querySelector("[data-ngdeploy]");
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
    sect.querySelectorAll(".ngform").forEach(row => {
      const host = row.querySelector('[data-ng="host"]')?.value || "";
      const auto = row.querySelector('[data-ng="cert"] option[value=""]');
      if (auto){ const k = nginxResolve(n, host.trim().toLowerCase()); auto.textContent = `443, ${k ? `${k}'s pair` : "no pair covers it yet"}`; }
    });
    nginxReadDraft(sect, n);
    // A route's Save wants a hostname and a port.
    const save = sect.querySelector(".ngform [data-ngsave]");
    if (save) save.disabled = !(nginxForm?.host?.trim() && nginxForm?.port);
    const d = nginxDraftOf(n), add = sect.querySelector("[data-ngcertsave]");
    if (add) add.disabled = !(d.cert.trim() && d.key.trim());
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
    const j = await nginxAct({action: "save", node: nid, routes: n.routes || [], drop_cert: k});
    if (!j.error){ nginxDraftOf(n).cert = nginxDraftOf(n).key = nginxDraftOf(n).certFor = ""; }
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
  // A route at a time: Add route and Edit open the one form, Cancel folds it
  // back, Save writes that route into the node's list and Delete takes it
  // out of it, each sent as the list with that one change.
  const open = i => { nginxEdit = {node: nid, i}; nginxForm = null; nginxRedraw(); };
  const shut = () => { nginxEdit = null; nginxForm = null; nginxRedraw(); };
  sect.querySelector("[data-ngadd]").onclick = () => open(-1);
  sect.querySelectorAll("[data-ngedit]").forEach(b => b.onclick = () => open(+b.dataset.ngedit));
  const form = sect.querySelector(".ngform");
  if (form){
    const i = +form.dataset.i;
    form.querySelector("[data-ngcancel]").onclick = shut;
    const save = form.querySelector("[data-ngsave]");
    nginxReadDraft(sect, n);
    save.disabled = !(nginxForm?.host?.trim() && nginxForm?.port);
    save.onclick = async () => {
      nginxReadDraft(sect, n);
      const routes = (n.routes || []).map(r => ({...r}));
      const r = {...nginxForm, host: nginxForm.host.trim()};
      if (i >= 0) routes[i] = r; else routes.push(r);
      busy(save, "Saving");
      const j = await nginxAct({action: "save", node: nid, routes});
      if (!j.error){ nginxEdit = null; nginxForm = null; }
      nginxRedraw();
    };
    const del = form.querySelector("[data-ngdel]");
    if (del) del.onclick = async () => {
      const r = (n.routes || [])[i] || {};
      if (!confirm(`Delete the route ${r.host === "*" ? "every name" : r.host}${r.path && r.path !== "/" ? r.path : ""} to port ${r.port}?`)) return;
      busy(del, "Deleting");
      const j = await nginxAct({action: "save", node: nid, routes: (n.routes || []).filter((_, k) => k !== i)});
      if (!j.error){ nginxEdit = null; nginxForm = null; }
      nginxRedraw();
    };
  }
  // Add a certificate unrolls the form; Add writes the pair beside the
  // routes as saved (an unsaved route is Routes' to save), Cancel lets the
  // paste go and rolls the form back up.
  const certOpen = sect.querySelector("[data-ngcertopen]");
  if (certOpen) certOpen.onclick = () => {
    nginxCertOpen = true;
    certOpen.closest(".ngcertadd").hidden = true;
    const form = sect.querySelector(".ngcertform");
    slideHidden(form, true, () => form.querySelector("#ngCert")?.focus());
  };
  const certSave = sect.querySelector("[data-ngcertsave]");
  if (certSave) certSave.onclick = async () => {
    nginxReadDraft(sect, n);
    const d = nginxDraftOf(n);
    busy(certSave, "Adding");
    const j = await nginxAct({action: "save", node: nid, routes: n.routes || [], cert: d.cert, key: d.key, cert_for: d.certFor});
    if (!j.error){
      // Where it was filed, since the key is the pair's own to say unless
      // a name was typed.
      if (j.host) notify(`${n.name}: the pair is kept as ${j.host}'s`);
      Object.assign(d, {cert: "", key: "", certFor: ""});
      nginxCertOpen = false;
    }
    nginxRedraw();
  };
  const certCancel = sect.querySelector("[data-ngcertcancel]");
  if (certCancel) certCancel.onclick = () => {
    nginxReadDraft(sect, n);
    Object.assign(nginxDraftOf(n), {cert: "", key: "", certFor: ""});
    nginxCertOpen = false;
    nginxRedraw();
  };
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
  const rm = sect.querySelector("[data-ngremove]");
  if (rm) rm.onclick = async e => {
    if (!confirm(`Remove nginx from ${n.name}?\n\nThe container comes down and leaves the Containers page; the routes and certificate stay here for a redeploy.`)) return;
    busy(e.target, "Removing");
    await nginxAct({action: "remove", node: nid});
    nginxRedraw();
  };
  sync();
}
