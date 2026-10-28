// The Installed page (R172, the operator, 28 Oct: a thing is configured
// where it is installed, not in the catalog): under Machines beside Nodes
// and Storage, one node picked, what is installed there by kind, each a
// row that opens on what the Library's card does not show: an agent's
// sign-in and what this person added to it, a toolchain's path, system
// packages and needs, the machine's own driver and toolkit, a pack's or a
// service's Configure from its config block, a job's error, and Remove.
// It reads the Library's read for the node (/api/library) and keeps only
// what is installed; the Library keeps Install.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Loaded
// before the page's own script, so everything here is a declaration.

"use strict";

let inst = null, instNode = "", instRev = 0, instSeq = 0, instLanded = 0, instFollow = null;
let instWantAgent = "";        // the agent whose row a door asked to open, until the rows land
const instOpen = new Set();    // the rows opened on their detail (rows-you-open)
const instDraft = {};          // what was typed into a Configure form and not saved yet, by row
const INST_KINDS = [["agent", "Coding agents"], ["toolchain", "Toolchains"], ["pack", "Tool packs"], ["service", "Services"]];

function openInstalledTab(){
  openTab({kind: "installed", arg: "__installed", label: "Installed"});
}
// ...on a node somebody named (a project's Sign in on NODE, the bell), the
// agent's row open on its sign-in once the rows land.
function openInstalledOn(id, agent = ""){
  if (id && id !== instNode){ instNode = id; inst = null; }
  if (agent) instWantAgent = agent;
  if (!(nodesList || []).some(n => n.id === id)) nodesStale = true;
  try{ localStorage.setItem("bb.instnode", id); }catch(e){ /* private */ }
  const was = location.hash;
  openInstalledTab();
  instRev++;
  const to = routeOf(tabOf(panes[0]));
  if (to && to !== was) shellPush(to);
  loadInstalled();
}

// The node the page opens on: the one it showed last, else the Library's,
// else the first agent node.
function instPick(){
  const live = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  let want = instNode;
  if (!live.some(n => n.id === want)){
    try{ want = localStorage.getItem("bb.instnode") || localStorage.getItem("bb.libnode") || ""; }catch(e){ want = ""; }
  }
  if (!live.some(n => n.id === want)) want = live[0]?.id || "";
  instNode = want;
  // The toolchain job's verbs act on tcNode; the pack dialogs read its rows.
  if (want && want !== tcNode){ tcNode = want; toolchains = null; }
  return live.find(n => n.id === want) || null;
}

async function loadInstalled(){
  const asked = ++instSeq;
  if (nodesList === null || nodesStale) await loadNodes();
  if (asked !== instSeq) return;
  if (!instPick()){
    inst = {nonode: true};
    instRev++; drawPanes();
    return;
  }
  const node = instNode;
  const keep = () => instNode === node && asked > instLanded;
  try{
    const r = await fetch("/api/library?node=" + encodeURIComponent(node));
    if (!r.ok) throw new Error("HTTP " + r.status);
    const got = await r.json();
    if (!keep()) return;
    inst = got;
  }catch(e){ if (!keep()) return; inst = {error: failWords(e)}; }
  instLanded = asked;
  if (!inst.error){
    tcSandboxNow = !!inst.sandbox; agYours = inst.yours || {plugins: [], mcp: {}};
    if (toolchains && !toolchains.nonode && !toolchains.error) toolchains.job = inst.job; else toolchains = {name: inst.name, job: inst.job, items: []};
    if (instWantAgent){
      const r = (inst.rows || []).find(x => x.kind === "agent" && x.agent === instWantAgent);
      if (r) instOpen.add(`agent:${r.name}`);
      instWantAgent = "";
    }
  }
  clearTimeout(instFollow); instFollow = null;
  if ((inst.rows || []).some(r => r.running)) instFollow = setTimeout(loadInstalled, 3000);
  instRev++;
  drawPanes();
}

// What is here: an installed row, the machine's own rows, a deployed
// service, and an agent whose card a person signs in on (Claude Code's,
// so a node without it still says where its sign-in would be).
function instHere(r){
  if (r.kind === "service") return true;
  if (r.machine) return true;
  if (r.kind === "agent") return r.installed || r.agent === "claude";
  return r.installed || r.unknown || r.running;
}

// Where it stands, in a few words at the row's right.
function instState(r){
  const w = (t, cls = "") => `<span class="state${cls ? " " + cls : ""}">${t}</span>`;
  if (r.running) return w(`${esc(r.doing === "remove" ? "removing" : r.doing === "check" ? "checking" : r.doing === "deploy" ? "deploying" : r.installed ? "updating" : "installing")}<span class="dots"></span>`);
  if (r.kind === "service") return r.installed ? w("deployed", "ok") : r.ready ? w(esc(r.ready), "warn") : w("configured, not deployed", "warn");
  if (r.machine){
    const m = r.machine, st = m.state;
    if (!m.managed) return w("installed by hand on this machine");
    if (r.name === TC_DRIVER) return st === "absent" ? w("not installed") : st === "loaded" ? w("running the card", "ok")
      : w(st === "nocard" ? "installed, no card now" : st === "leaving" ? "removed, until a restart" : m.newer ? "update available" : "installed, takes the card at a restart", "warn");
    return st === "absent" ? w("not installed") : st === "ready" ? w(m.driver_loaded ? "ready" : "installed, needs the driver running", m.driver_loaded ? "ok" : "warn")
      : w(st === "nocard" ? "installed, no card now" : "installed, Docker not configured", "warn");
  }
  if (r.kind === "agent" && !r.installed) return w("not installed: the Library installs it", "warn");
  if (r.installed) return w(r.update ? `update available: ${esc(r.latest)}` : "installed", r.update ? "warn" : "ok");
  if (r.unknown) return w("installed, version unknown");
  return w("");
}

// The row's verbs: Remove where it is here (a pack's Remove is the
// dialog's own, which asks where it is still installed), and a service's
// Install once something is behind it.
function instActs(r, may){
  const a = (act, words, cls = "") => `<button type="button"${cls ? ` class="${cls}"` : ""} data-instact="${act}" data-instkind="${esc(r.kind)}" data-instname="${esc(r.name)}">${esc(words)}</button>`;
  if (r.running) return "";
  if (r.kind === "service") return !may.apps ? "" : r.installed ? a("remove", "Remove", "danger")
    : `<button type="button" class="primary" data-instact="install" data-instkind="service" data-instname="${esc(r.name)}"${r.ready ? " disabled" : ""}${r.ready ? ` title="${esc(r.ready)}"` : ""}>Install</button>`;
  if (r.machine) return r.machine.managed && r.installed && may.install ? a("remove", "Remove", "danger") : "";
  if (!may.install) return "";
  if (r.kind === "pack" && r.pack) return `${a("edit", "Edit")}${r.installed ? a("remove", "Remove", "danger") : ""}`;
  return r.installed ? a("remove", "Remove", "danger") : "";
}

// The open row: what the node knows of it, and what a person sets here.
let agYours = {plugins: [], mcp: {}};   // this account's plugins and MCP servers on the node, as the read last said

// What this account added to an agent on the node (R95 step 15, moved here
// from Profile; the Agents page's until R170): Claude Code's plugins, and
// each agent's MCP servers, by name, as the node last said. Read here;
// changed in a session.
function agExtras(a){
  const pl = a.id === "claude" ? (agYours.plugins || []) : [];
  const mcp = (agYours.mcp || {})[a.id] || [];
  const one = p => `<code>${esc(p.id.replace(/@claude-plugins-official$/, ""))}</code>${p.version ? ` ${esc(p.version)}` : ""}${
    p.scope === "project" ? ` (${esc(p.project ? projLabel(p.project) : "a project")})` : ""}${p.enabled === false ? ` <span class="dim">off</span>` : ""}`;
  const rows = [
    a.id === "claude" ? ["your plugins", pl.length ? pl.map(one).join(", ") : "none", {html: true}] : null,
    ["your MCP servers", mcp.length ? mcp.map(x => `<code>${esc(x)}</code>`).join(", ") : "none", {html: true}],
  ].filter(Boolean);
  return `<div class="field agpart"><div class="fsub">Yours</div>${factGrid(rows, "agextras")}<div class="hint">${
    a.id === "claude" ? "Changed with <code>/plugin</code> and <code>/mcp</code> in a Claude session, for you alone."
      : `Set up in ${esc(a.product)}'s own configuration, for you alone.`}</div></div>`;
}

function instDetail(r){
  const n = (nodesList || []).find(x => x.id === instNode);
  const lines = [];
  if (r.machine){
    lines.push(r.name === TC_DRIVER ? tcDriverLine(r.machine) : tcToolkitLine(r.machine));
    if (!r.machine.managed) lines.push(`<span class="sub warn">This machine is its owner's, not a BuilderBot sandbox: ${r.name === TC_DRIVER ? "its driver" : "the toolkit"} is installed there by hand.</span>`);
    if (r.machine.settling) lines.push(`<span class="sub">The node is reporting what the last job left<span class="dots"></span></span>`);
    return lines.filter(Boolean).join("");
  }
  if (r.kind === "toolchain" || r.kind === "pack"){
    if (r.tool) lines.push(`<span class="sub">Adds <code>bb tool ${esc(r.tool)}</code> to a session.</span>`);
    if (r.needs?.length) lines.push(`<span class="sub">Needs ${esc(r.needs.join(", "))}, installed with it.${r.needed_by?.length ? ` Needed by ${esc(r.needed_by.join(", "))}.` : ""}</span>`);
    else if (r.needed_by?.length) lines.push(`<span class="sub">Needed by ${esc(r.needed_by.join(", "))}.</span>`);
    lines.push(tcSystemLine(r, !!inst?.managed));
    lines.push(tcNeedsLine(r));
    if (r.path) lines.push(`<span class="sub">At ${esc(r.path)}.</span>`);
    lines.push(tcVerifiedLine(r));
    if (r.reopen) lines.push(`<span class="sub warn">${r.reopen === 1 ? "1 session" : `${r.reopen} sessions`} open here started before this was installed: reopen ${r.reopen === 1 ? "it" : "them"} to use it.</span>`);
    if (r.pinned?.length) lines.push(`<span class="sub">Pinned by ${esc(r.pinned.map(projLabel).join(", "))}.</span>`);
    if (r.pack) lines.push(`<span class="sub">${r.pack.here ? "Made here" : `From <code>${esc(r.pack.url)}</code> at ${esc((r.pack.commit || "").slice(0, 12))}`}${r.pack.by ? `, added by ${esc(r.pack.by)}` : ""}.</span>`);
    if (r.config?.length && r.values && inst?.may?.packs) lines.push(instConfigForm(r));
  }
  if (r.kind === "service"){
    lines.push(instServiceLines(r));
    lines.push(instConfigForm(r));
  }
  if (r.kind === "agent"){
    const a = agentById(r.agent);
    lines.push(`<span class="sub">${a?.product ? `${esc(a.product)}, installed` : "Installed"} for the node's session account; ${r.latest ? `the latest is ${esc(r.latest)}` : "its latest is not known yet"}.${
      a?.provider ? ` Signs in with ${/^(?:[AEIOU]|x(?=[A-Z]))/.test(a.provider) ? "an" : "a"} ${esc(a.provider)} account.` : ""}</span>`);
    if (r.error) lines.push(`<span class="sub bad">${esc(r.error)}</span>`);
    if (r.agent === "open"){
      const rt = (inst?.rows || []).find(x => x.kind === "service" && x.service === "router");
      lines.push(rt?.installed ? `<span class="sub">Runs through the model router on this node${(rt.status?.models || []).length ? `, ${rt.status.models.filter(m => !m.wild).length} models known` : ""}.</span>`
        : `<span class="sub warn">Needs the model router on this node: under Services here.</span>`);
    }
    if (n && (r.installed || r.agent === "claude") && typeof signinBlock === "function" && a?.provider)
      lines.push(`<div class="field agpart"><div class="fsub">Your sign-in</div>${signinBlock(n, r.agent)}</div>`);
    if (n && r.installed && a) lines.push(agExtras(a));
  }
  return lines.filter(Boolean).join("");
}

// What a pack or a service asks for on this node (R172): its config block
// as a form, the answers as the page may see them (a secret only as set:
// typed to replace, "clear" to take it out), Save to the card's own route.
function instConfigField(f, v, key){
  const id = `ic-${key}-${f.name}`.replace(/[^A-Za-z0-9_-]/g, "_");
  const at = `data-icf="${esc(f.name)}"`;
  const label = lbl(id, f.label, f.help || "");
  switch (f.kind){
    case "secret": return `<div class="field setrow col ctlrow">${label}<input id="${id}" type="password" ${at} autocomplete="off" spellcheck="false" placeholder="${v ? "set: type to replace, or 'clear'" : f.required ? "required" : ""}"></div>`;
    case "text": return `<div class="field setrow col ctlrow">${label}<input id="${id}" type="text" ${at} autocomplete="off" spellcheck="false" value="${esc(v || "")}"></div>`;
    case "switch": return `<div class="field"><label class="ndcap"><input id="${id}" type="checkbox" ${at}${v ? " checked" : ""}> ${esc(f.label)}${f.help ? helpIcon(f.help) : ""}</label></div>`;
    case "choice": return `<div class="field setrow col ctlrow">${label}<select id="${id}" ${at}>${(f.choices || []).map(c => `<option value="${esc(c.value)}"${c.value === v ? " selected" : ""}>${esc(c.label)}</option>`).join("")}</select></div>`;
    case "projects": {
      const all = (inst?.rows || []).find(x => x.kind === "service")?.all_projects || [];
      return `<div class="field"><div class="fsub">${esc(f.label)}${f.help ? helpIcon(f.help) : ""}</div><div class="chips">${all.length ? all.map(p => `<label class="chip"><input type="checkbox" data-icproj="${esc(f.name)}" value="${esc(p)}"${(v || []).includes(p) ? " checked" : ""}> ${esc(p)}</label>`).join("") : `<span class="dim">no projects yet</span>`}</div></div>`;
    }
    case "list": {
      const rows = (v || []).map((row, j) => `<div class="field ctlrow icrow" data-iclist="${esc(f.name)}" data-icrow="${j}">${
        (f.fields || []).map(sf => sf.kind === "secret"
          ? `<input type="password" data-icsub="${esc(sf.name)}" placeholder="${row[sf.name] ? "set: type to replace" : esc(sf.label)}" autocomplete="off" spellcheck="false" aria-label="${esc(sf.label)}">`
          : `<input type="text" data-icsub="${esc(sf.name)}" placeholder="${esc(sf.help || sf.label)}" value="${esc(row[sf.name] || "")}" autocomplete="off" spellcheck="false" aria-label="${esc(sf.label)}">`).join("")}
        <button type="button" data-icrm="${esc(f.name)}" data-icrow="${j}">Remove</button></div>`).join("");
      return `<div class="field"><div class="fsub">${esc(f.label)}${f.help ? helpIcon(f.help) : ""}</div></div>${rows}<div class="field"><div class="addbar ctlrow"><button type="button" data-icadd="${esc(f.name)}">Add a row</button></div></div>`;
    }
    default: return "";
  }
}
function instConfigForm(r){
  if (!r.config?.length) return "";
  const key = `${r.kind}:${r.name}`, v = instDraft[key] || r.values || {};
  return `<div class="field agpart icform" data-icform="${esc(key)}"><div class="fsub">Configure on ${esc(inst?.name || "this node")}</div>
    ${r.config.map(f => instConfigField(f, v[f.name], key)).join("")}
    <div class="actbar"><span class="state">${r.kind === "service" && r.installed ? "saving rebuilds it with the change" : ""}</span><button type="button" class="primary" data-icsave="${esc(key)}">Save</button></div></div>`;
}
function instConfigRead(form, r){
  const v = {};
  for (const f of r.config || []){
    if (f.kind === "secret" || f.kind === "text" || f.kind === "choice") v[f.name] = form.querySelector(`[data-icf="${CSS.escape(f.name)}"]`)?.value ?? "";
    else if (f.kind === "switch") v[f.name] = !!form.querySelector(`[data-icf="${CSS.escape(f.name)}"]`)?.checked;
    else if (f.kind === "projects") v[f.name] = [...form.querySelectorAll(`[data-icproj="${CSS.escape(f.name)}"]:checked`)].map(i => i.value);
    else if (f.kind === "list") v[f.name] = [...form.querySelectorAll(`.icrow[data-iclist="${CSS.escape(f.name)}"]`)].map(row =>
      Object.fromEntries((f.fields || []).map(sf => [sf.name, row.querySelector(`[data-icsub="${CSS.escape(sf.name)}"]`)?.value ?? ""])));
  }
  return v;
}
// What a service says of itself here: the router's address, the models
// known and the spend with the presses that read them again, and Ollama's
// models pulled and removed.
function instServiceLines(r){
  const st = r.status || {};
  if (r.service !== "router") return "";
  // What it is was said above the row (the catalog's line, B431): only what
  // Install does is said here.
  if (!r.installed) return `<span class="sub">Install deploys it as a written container once something is behind it: a provider key, an endpoint of your own, or Ollama.</span>`;
  const models = (st.models || []).filter(m => !m.wild);
  const pulled = (st.ollama?.models || []).map(m => `<div class="row"><span class="grow">${esc(m)}</span><button type="button" data-instsvc="ollama-remove" data-instmodel="${esc(m)}">Remove</button></div>`).join("");
  return `<span class="sub">LiteLLM answers at <code>${esc(st.url || "")}/v1</code> for the projects allowed, each with a key of its own.</span>
    <div class="actbar"><span class="state">${models.length ? `${models.length} model${models.length === 1 ? "" : "s"} known${st.models_at ? `, read ${esc(ago(st.models_at))}` : ""}` : "no models read yet"}${
      Object.keys(st.spend || {}).length ? ` · spent ${Object.entries(st.spend).map(([p, s]) => `${esc(p)} $${Number(s).toFixed(2)}`).join(", ")}` : ""}</span>
      <button type="button" data-instsvc="models">Read the models</button><button type="button" data-instsvc="spend">Read the spend</button></div>
    ${st.ollama?.on ? `<div class="field"><div class="ctlrow"><input type="text" data-instpull placeholder="a model Ollama lists, such as qwen2.5-coder:7b" autocomplete="off" spellcheck="false">
      <button type="button" data-instsvc="ollama-pull">Pull</button></div>${pulled ? `<div class="rows">${pulled}</div>` : `<div class="sub dim">Nothing pulled yet.</div>`}</div>` : ""}`;
}

function instRow(r, may){
  const key = `${r.kind}:${r.name}`, open = instOpen.has(key);
  const ver = r.version && r.version !== "-" && r.version !== "present" ? ` <span class="pill" title="installed">${esc(r.version)}</span>` : "";
  const err = !r.running && (r.kind === "toolchain" || r.kind === "pack") && inst?.job?.errors?.[r.name] ? `<div class="sub bad">${esc(inst.job.errors[r.name])}</div>` : "";
  return `<div class="row irow${open ? " open" : ""}" data-irow="${esc(key)}"><div class="grow">
      <div class="name">${esc(r.label)}${ver}${r.update && r.latest ? ` <span class="pill warn">${esc(r.latest)} is out</span>` : ""} <button type="button" class="link imore" data-instmore="${esc(key)}" aria-expanded="${open}">${open ? "Less" : "Details"}</button></div>
      <div class="sub iabout">${esc(r.about)}</div>
      <div class="idetail">${open ? instDetail(r) : ""}</div>${err}
    </div><div class="acts">${instState(r)}${instActs(r, may)}</div></div>`;
}

function renderInstalledInto(i){
  const d = docSurface(i, "installed");
  if (!d) return;
  if (inst === null){
    d.setBar("");    // the node is the Machines header's (R177)
    d.list.innerHTML = skTpl(pageHead({title: GHOST, facts: [["Installed", GHOST], ["Updates due", GHOST]]})
      + INST_KINDS.map(([k, title]) => docSection("installed", k, title, "", skRows(2))).join(""));
    if (!instSeq) loadInstalled();
    return;
  }
  const pnodes = (nodesList || []).filter(x => x.kind === "agent" && x.state !== "retired").map(x => ({id: x.id, name: x.name, live: x.live}));
  if (inst.nonode){
    d.setBar("");
    d.list.innerHTML = noNodeYet("toolchains and coding agents install on a node", "instnone");
    return;
  }
  const may = inst.may || {};
  d.setBar("");    // the node is picked in the Machines group's header (R177)
  if (inst.error){
    paint(d.list, `<div class="field"><div class="notice bad">${esc("could not read what is installed: " + inst.error)}</div></div>`);
    return;
  }
  const rows = (inst.rows || []).filter(instHere);
  const due = rows.filter(r => r.update).length;
  const unmet = Object.entries(inst.sysdeps?.unmet || {});
  const notes = unmet.length ? `<div class="field"><div class="notice warn instsys">System packages ${esc(inst.name || "this node")} lacks for what its store holds (${esc(inst.sysdeps.family || "")}): ${
      unmet.map(([r, ps]) => `${esc(r)}: ${esc(ps.join(" "))}`).join("; ")}. ${inst.sandbox && may.install
        ? `<button type="button" data-instsysdeps${inst.job?.running ? " disabled" : ""} title="install these on ${esc(inst.name || "the node")} without reinstalling the toolchains">Install system packages</button>`
        : "This node's owner installs them: the agent does not administer the machine."}</div></div>` : "";
  const head = pageHead({title: inst.name || "", facts: [
    ["Installed", String(rows.filter(r => r.installed).length)],
    ["Updates due", due ? String(due) : ""],
    ["Store", inst.store?.root || ""],
  ]});
  const sects = INST_KINDS.map(([k, title]) => {
    const here = rows.filter(r => r.kind === k);
    if (!here.length) return "";
    const body = `<div class="rows">${here.map(r => instRow(r, may)).join("")}</div>`;
    return docSection("installed", k, title, k === "agent" ? `${here.filter(r => r.installed).length} of ${here.length}` : String(here.length), body);
  }).join("") || `<div class="empty">Nothing installed on ${esc(inst.name || "this node")} yet: the Library installs toolchains, coding agents and packs there.</div>`;
  paint(d.list, `<div data-instnode="${esc(instNode)}">${notes}${head}${sects}</div>`);
  wireInstalled(d.el);
}

function wireInstalled(root){
  wireSections(root);
  if (typeof wireSignin === "function") wireSignin(root);
  root.querySelectorAll("[data-instmore]").forEach(b => b.onclick = () => {
    const k = b.dataset.instmore;
    if (instOpen.has(k)) instOpen.delete(k); else instOpen.add(k);
    instRev++; drawPanes();
  });
  root.querySelectorAll("[data-tcsys]").forEach(b => b.onclick = async () => { await tcAct("sysdeps", [b.dataset.tcsys]); loadInstalled(); });
  root.querySelectorAll("[data-tcneed]").forEach(b => b.onclick = async () => { await tcAct("install", [b.dataset.tcneed]); loadInstalled(); });
  const sd = root.querySelector("[data-instsysdeps]");
  if (sd) sd.onclick = () => pressing(sd, async () => { busy(sd, "Installing"); await tcAct("sysdeps"); await loadInstalled(); });
  root.querySelectorAll(".icform").forEach(form => {
    const key = form.dataset.icform, r = (inst?.rows || []).find(x => `${x.kind}:${x.name}` === key);
    if (!r) return;
    const read = () => { instDraft[key] = instConfigRead(form, r); return instDraft[key]; };
    // A secret typed and not saved comes back after a redraw (a row added,
    // a poll): a password field is drawn empty, so the draft fills it.
    const dr = instDraft[key];
    if (dr) for (const f of r.config || []){
      if (f.kind === "secret" && typeof dr[f.name] === "string" && dr[f.name]){ const i = form.querySelector(`[data-icf="${CSS.escape(f.name)}"]`); if (i && !i.value) i.value = dr[f.name]; }
      if (f.kind === "list") form.querySelectorAll(`.icrow[data-iclist="${CSS.escape(f.name)}"]`).forEach((row, j) => {
        for (const sf of f.fields || []) if (sf.kind === "secret" && typeof dr[f.name]?.[j]?.[sf.name] === "string" && dr[f.name][j][sf.name]){
          const i = row.querySelector(`[data-icsub="${CSS.escape(sf.name)}"]`); if (i && !i.value) i.value = dr[f.name][j][sf.name]; }
      });
    }
    form.addEventListener("input", read);
    form.addEventListener("change", read);
    form.querySelectorAll("[data-icadd]").forEach(b => b.onclick = () => { const v = read(); v[b.dataset.icadd] = [...(v[b.dataset.icadd] || []), {}]; instRev++; drawPanes(); });
    form.querySelectorAll("[data-icrm]").forEach(b => b.onclick = () => { const v = read(); v[b.dataset.icrm].splice(Number(b.dataset.icrow), 1); instRev++; drawPanes(); });
    const save = form.querySelector("[data-icsave]");
    if (save) save.onclick = () => pressing(save, async () => {
      busy(save, "Saving");
      const j = await (await postJSON("/api/library", {action: "configure", node: instNode, pack: r.name, values: read()})).json().catch(() => ({error: "no answer"}));
      if (j.error){ notify(j.error, true); return; }
      delete instDraft[key];
      notify(j.job ? "saved: the router is rebuilt with the change, its row on the Containers page has the build" : "saved");
      await loadInstalled();
    });
  });
  root.querySelectorAll("[data-instsvc]").forEach(b => b.onclick = () => pressing(b, async () => {
    const row = b.closest(".irow"), r = (inst?.rows || []).find(x => `${x.kind}:${x.name}` === row?.dataset.irow);
    if (!r) return;
    const act = b.dataset.instsvc;
    busy(b, act === "ollama-pull" ? "Pulling" : act === "ollama-remove" ? "Removing" : "Reading");
    const model = act === "ollama-pull" ? row.querySelector("[data-instpull]")?.value || "" : b.dataset.instmodel || "";
    const j = await (await postJSON("/api/library", {action: act, node: instNode, pack: r.name, model})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true); else if (act === "ollama-pull") notify(`pulling ${model}: a job on the Jobs page`);
    await loadInstalled();
  }));
  root.querySelectorAll("[data-instact]").forEach(b => b.onclick = () => instAct(b, b.dataset.instact, b.dataset.instkind, b.dataset.instname));
}

async function instAct(b, act, kind, name){
  const r = (inst?.rows || []).find(x => x.kind === kind && x.name === name);
  if (!r) return;
  const where = (nodesList || []).find(x => x.id === instNode)?.name || "this node";
  if (kind === "service"){
    if (act === "remove" && !await askYes(`Remove ${r.label} from ${where}? Its keys stay here sealed; the projects lose their way to it.`, {verb: "Remove", danger: true})) return;
    busy(b, act === "remove" ? "Removing" : "Deploying");
    const j = await (await postJSON("/api/library", {action: act, node: instNode, pack: r.name})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else if (j.job) notify(`${act === "remove" ? "removing" : "deploying"} ${r.label}: its row on the Containers page has the build`);
    await loadInstalled();
    return;
  }
  if (kind === "agent"){
    if (!await askYes(`Remove ${r.label} from ${where}? Its sessions end, and none starts there until it is installed again.`)) return;
    busy(b, "Removing");
    const j = await (await postJSON("/api/agents", {action: "remove", node: instNode, agent: r.agent || ""})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    await loadInstalled();
    return;
  }
  if (act === "edit"){
    if (!toolchains || toolchains.nonode || toolchains.error || tcNode !== instNode) await loadToolchains();
    tpOpen(r.name);
    return;
  }
  if (!await askYes(`Uninstall ${r.label} from ${where}? The files are deleted; installing it again re-downloads them.`)) return;
  busy(b, "Removing");
  await tcAct("remove", [r.name]);
  await loadInstalled();
}
