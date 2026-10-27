// A project's settings dialog: its name, its nodes, the model and effort
// every session starts on, its color, the dials of what an agent may do
// there, the git credential, and the submit that applies each change in
// turn. Unlinking and deleting a project start here too.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- a project's settings: model, effort, color and the dials ----------

// The Claude card: the standing model/effort every send applies. Options are
// the same tables the send box used to carry; "Claude's default" is the empty
// value, which sends no switch at all.
// What each policy MEANS, since the stored word is a permission level and
// the question the operator is answering is "how much of this may Claude
// move?". The values are unchanged: only the reading is.
const POLICY_LABEL = {
  locked: "locked, only me",
  // Creating the first version and moving one after are different
  // decisions: the first has nothing to overwrite. This is the one that
  // delegates only that.
  start: "may start one, not move it",
  patch: "patch only",
  minor: "patch and minor",
  open: "anything, including major",
};
const MODELS = [["", "Claude's default"], ["opus", "Opus"], ["sonnet", "Sonnet"],
                ["haiku", "Haiku"], ["fable", "Fable"]];
const EFFORTS = [["", "Claude's default"], ["low", "low"], ["medium", "medium"],
                 ["high", "high"], ["xhigh", "xhigh"], ["max", "max"]];
// What the dialog was opened showing, so Save can tell a real change from a
// dialog that was merely looked at: the difference decides whether a running
// session is restarted, which is not something to do because somebody opened
// a menu.
let rnPrefWas = {git_name: "", git_email: "",
                 node: "", nodes: "", hosts: "", reads: "", tc_off: "", packs_on: "", sees: "", reaches: "", build: "", test: "", outputs: "",
                 capture_days: "7", snapshot_days: "14", snapshots_on: "1", dev_keep: "3", gate: ""};
// The colors a project can be, by the names prefs.py stores (COLORS there)
// and the tone each is drawn in. Named at the store and mapped here so the
// tone can be retuned for a scheme without touching what anybody saved.
const PROJECT_COLORS = [["", ""], ["red", "#e5534b"], ["orange", "#e8883a"],
                        ["yellow", "#d4b33a"], ["green", "#57ab5a"], ["teal", "#39b5b0"],
                        ["blue", "#539bf5"], ["violet", "#a371f7"], ["pink", "#e0669e"]];
const colorTone = name => (PROJECT_COLORS.find(([n]) => n === name) || [])[1] || "";
// The class and variable an element wears for a project's color, or
// nothing for a project with none.
const colorAttrs = name => {
  const tone = colorTone(name);
  return tone ? {cls: " pc", style: ` style="--pc:${tone}"`} : {cls: "", style: ""};
};
// This account's color for a project (the operator, 18 Oct: a person's own,
// set from its card), or "", by its project's key or any of its repositories.
const projectColor = name => state?.repos?.[name]?.color
  ?? (state?.projects || []).find(x => x.name === name)?.color ?? "";
// The name a project is shown under (R154): its directory is `name` and the
// key everywhere, and what a person reads is the registry's `label`. A name
// not in the poll (a project since deleted) is shown as it is. A project's
// own key (R138) reads as the project's name.
const projLabel = name =>
  (state?.projects || []).find(x => x.name === name)?.label || state?.repos?.[name]?.name || String(name ?? "");
// The project a tab is about, for its color: a notebook's, the project whose
// Claude session a terminal tab holds, or for a shell the project its label
// names, the directory it is in (sessionLabels), so a tab that reads
// "sh: droid" wears droid's color wherever it was opened (the operator, 18
// Oct). Before the poll has its directory, the project it was opened on
// (sh:N:NAME). A container's shell and one outside every project have none.
const tabProject = t => {
  if (t.kind === "notebook") return t.arg;
  const a = String(t.kind === "term" ? t.arg : "");
  if (agentOfArg(a)) return agentOfArg(a).project;
  if (a.startsWith("ctr:") || !a) return "";
  const cwd = (state?.sessions || []).find(s => s.name === sessionOf(a))?.cwd;
  if (!cwd) return a.startsWith("sh:") ? a.split(":")[2] || "" : "";
  const here = baseOf(cwd);
  return (state?.projects || []).some(p => p.name === here) ? here : "";
};
// The gate's three pickers, one per notebook tab (roadmap #27).
const GATE_MODES = [["auto", "auto"], ["ask", "ask me"], ["deny", "deny"]];
// A dial's choices beyond those three, by the kind it gates: the wiki may
// also be hidden, kept from a session altogether, reading included
// (prefs.GATE_EXTRA; the operator, 2 Oct).
const GATE_EXTRA = {wiki: [["hidden", "hidden"]]};
const gateChoices = k => [...GATE_MODES, ...(GATE_EXTRA[k] || [])];
const GATE_IDS = {roadmap: "rnGateRoadmap", bugs: "rnGateBugs", rules: "rnGateRules", settings: "rnGateSettings",
                  design: "rnGateDesign", wiki: "rnGateWiki"};
const rnGateNow = () => Object.fromEntries(
  Object.entries(GATE_IDS).map(([k, id]) => [k, $(id).value || "auto"]));
const gateKey = g => Object.keys(GATE_IDS).map(k => g?.[k] || "auto").join(",");

// A project's settings as the form holds them, from its row: what the form
// opens on, and what a section's Save compares with what is saved now.
function rnPrefsOf(p){
  return {git_name: p?.yours?.git_name || "", git_email: p?.yours?.git_email || "",
               node: p?.prefs?.node || "",
               nodes: (p?.prefs?.nodes || []).join(","),
               hosts: (p?.prefs?.hosts || []).join(","),
               reads: (p?.prefs?.reads || []).join(","),
               tc_off: (p?.prefs?.tc_off || []).join(","), packs_on: (p?.prefs?.packs_on || []).join(","),
               agents_off: (p?.prefs?.agents_off || []).join(","),
               agent_default: p?.prefs?.agent_default || "claude",
               agent_slots: String(p?.prefs?.agent_slots ?? 3),
               sees: (p?.prefs?.sees || []).join(", "),
               reaches: JSON.stringify(p?.prefs?.reaches || []),
               build: p?.prefs?.build || "", test: p?.prefs?.test || "",
               outputs: (p?.prefs?.outputs || []).join(", "),
               capture_days: String(p?.prefs?.capture_days ?? 7),
               snapshot_days: String(p?.prefs?.snapshot_days ?? 14),
               snapshots_on: p?.prefs?.snapshots_on === false ? "0" : "1",
               dev_keep: String(p?.prefs?.dev_keep ?? 3),
               gate: gateKey(p?.prefs?.gate),
               tests_in: p?.prefs?.tests_in || "node",
               test_change: p?.prefs?.test_change || "wait",
               gpu: p?.prefs?.gpu || "on",
               reply: p?.yours?.reply || "", asks: p?.yours?.asks || "", term_scheme: p?.yours?.term_scheme || "",
               devbuild: devClaudeMode(p?.name || rnFor),
               makevms: p?.prefs?.makevms || "deny",
               vm_caps: rnVmCapsOf(p),
               report: p?.prefs?.report || "auto",
               sign: p?.prefs?.sign || "ask",
               release: p?.prefs?.release || "ask",
               keys: p?.prefs?.keys || "ask",
               pc: p?.prefs?.pc || "deny",
               version: p?.version_policy || "locked"};
}

function rnFillPrefs(p){
  // A fresh open draws the node list from what is saved, not from the ticks
  // the last project's dialog left in it (the merged list, 13 Oct).
  const nm = $("rnNodesMore");
  if (nm) delete nm.dataset.drawn;
  rnPrefWas = rnPrefsOf(p);
  // A select with no value of its own reads as its first option, and the
  // form collects every field whichever section is saved: set here, with the
  // rest that are always on the form, so saving another section never takes
  // the cap down to 1 (R143).
  $("rnAgentSlots").value = rnPrefWas.agent_slots;
  $("rnGitName").value = rnPrefWas.git_name;
  $("rnGitEmail").value = rnPrefWas.git_email;
  // Said where it is typed: the Profile is the default, this is the exception,
  // and a commit needs both halves from somewhere.
  $("rnGitHint").textContent = rnPrefWas.git_name || rnPrefWas.git_email
    ? "Your commits here use these instead of your Profile."
    : "Empty uses your Profile. Set these to commit here under a different name.";
  $("rnSees").value = rnPrefWas.sees;
  // The last project's rows go before this one's draft is drawn, or the
  // first draw would read them back into it.
  $("rnReachRows").innerHTML = "";
  rnReachDraft = JSON.parse(rnPrefWas.reaches || "[]");
  rnFillNode();
  rnFillPrefsRest(p);
  rnFillReads();
  rnFillAgents();
  rnLoadTools(p);
  rnLockSettings(p);
}

// The project's own sections, read only for an account whose roles do not
// hold Project settings (B19): every control in them dead, and why said on
// each in red, not in a tooltip. Just for you stays live, being the
// account's own; Snapshots and Running sessions say their own reasons.
const RN_LOCKED_SAID = "Read only for you: changing these needs a role that holds Project settings on this project.";
function rnLockSettings(p){
  const locked = p?.may_settings === false;
  document.querySelectorAll("details.rngroup").forEach(d => {
    const k = (d.dataset.sect || "").replace(/^rn:/, "");
    if (["yours", "snapshots", "sessions"].includes(k)) return;
    const body = d.querySelector(":scope > .body");
    if (!body) return;
    body.querySelector(":scope > .rnlocked")?.remove();
    body.querySelectorAll("input, select, textarea, button").forEach(c => {
      if (locked && !c.disabled){ c.disabled = true; c.dataset.rnlock = "1"; }
      else if (!locked && c.dataset.rnlock){ c.disabled = false; delete c.dataset.rnlock; }
    });
    if (locked) body.insertAdjacentHTML("afterbegin", `<div class="field rnlocked"><div class="hint">${esc(RN_LOCKED_SAID)}</div></div>`);
  });
}

// The project's node: every node but this container, because local can
// host neither a build (no workspace of its own) nor, on purpose, a
// docker daemon. Shown when there is one to pick; "none" is spelled as an
// option so clearing the binding is a pick rather than a mystery.
//
// The list arrives on its own schedule. The first dialog opened after a
// page load is the one that asks for it, and it fills the picker when the
// answer lands rather than on the next opening, which is what a dialog
// that showed no node until it was closed and opened again was: a
// container restart, then the first press of Settings.
function rnFillNode(){
    const sel = $("rnNode"), wrap = $("rnNodeField");
    // A node un-enrolled is out of every picker, by the node list's word or,
    // where that list is from before the removal, by the project rows' (the
    // server marks a row whose node was removed).
    const removed = new Set((state?.projects || []).filter(p => p.node_removed).map(p => p.prefs?.node).filter(Boolean));
    // A disabled node is kept but not offered (the operator, 11 Oct), unless
    // it is this project's already, which the row then says.
    // ...and a hosting-only node is not offered as the primary (the operator,
    // 14 Oct): it holds no code and runs no session, so it is a row under
    // Also works on, marked Hosting only, and nothing else.
    const pick = (nodesList || []).filter(n => n.kind !== "local" && n.state !== "retired"
      && (n.state !== "disabled" || n.id === rnPrefWas.node) && !removed.has(n.id) && !n.config?.host_only);
    if (nodesList === null){
      const opened = rnFor;
      loadNodes().then(() => { if (opened !== null && rnFor === opened){ rnFillNode(); rnBars(); } });
    }
    // Hidden with the rest of the project's own settings when this dialog was
    // opened by the chain, which asks about the remote and nothing else.
    wrap.hidden = rnMode === "git" || !pick.length;
    // Shown to everybody on the project and changed by grant (R137 step 4):
    // a node is shared, so the picker is read-only without `node`.
    sel.disabled = state?.can?.node === false;
    // The places a session is shown are places on a node, so the field is
    // there when a node is.
    $("rnSeesField").hidden = $("rnReachField").hidden = wrap.hidden;
    // What each node carries, on its own option: the node does everything
    // for this project, so the only question left is what is installed on it.
    const tools = n => Object.keys(n.reported?.toolchains || {});
    // The node this project was on, when it has since been un-enrolled: kept,
    // selected and marked "(removed)" in italics, so the person sees where it
    // used to run (the operator, 5 Oct). Offered on this project's picker
    // only, never on another's.
    const row = (state?.projects || []).find(p => p.name === rnFor);
    const gone = row?.node_removed && rnPrefWas.node && !pick.some(n => n.id === rnPrefWas.node)
      ? `<option value="${esc(rnPrefWas.node)}" class="removed" selected>${esc(row.node_name || rnPrefWas.node)} (removed)</option>` : "";
    sel.innerHTML = `<option value="">none: no builds, tests or sessions until one is picked</option>`
      + gone
      + pick.map(n => `<option value="${esc(n.id)}"${n.id === rnPrefWas.node ? " selected" : ""}>${
          esc(n.name)} (${n.config?.own ? "this machine, " : ""}${esc(n.kind)}, ${esc(n.state)}${n.live === false ? ", quiet" : ""}${
          tools(n).length ? " · " + esc(tools(n).slice(0, 4).join(", ")) : ""})</option>`).join("");
    sel.value = gone ? rnPrefWas.node : pick.some(n => n.id === rnPrefWas.node) ? rnPrefWas.node : "";
    // The closed picker is italic while the removed node is the one shown.
    sel.classList.toggle("removed", !!gone && sel.value === rnPrefWas.node);
    // ...and the field shows for it even when no other node is enrolled.
    if (gone) wrap.hidden = $("rnSeesField").hidden = $("rnReachField").hidden = rnMode === "git";
    rnFillNodesMore();
}

// Which of the rows under Also works on are hosting-only nodes (prefs.hosts
// rather than prefs.nodes): the ones the node list marks so, and a named
// one that is gone or no longer hosting-only, kept ticked so Save does not
// drop it without anybody seeing.
function rnHostIds(){
  const was = rnPrefWas.hosts.split(",").filter(Boolean);
  const marked = (nodesList || []).filter(n => n.config?.host_only).map(n => n.id);
  return new Set([...marked, ...was.filter(id => !(nodesList || []).some(n => n.id === id && !n.config?.host_only))]);
}

// Also reaches (the operator, 7 Oct): addresses a session here may still
// reach where its node filters, each on the project's nodes ticked beside
// it, every one when the project is on one node. A draft until Save; all
// ticked is stored as none named, which also covers a node added later.
let rnReachDraft = [];

function rnReachNodes(){
  const primary = $("rnNode").value;
  // The nodes a session may run on: a hosting-only row holds no session.
  const hosts = rnHostIds();
  const more = [...$("rnNodesMore").querySelectorAll("input:checked")].map(i => i.value).filter(id => !hosts.has(id));
  const ids = primary ? [primary, ...more.filter(x => x !== primary)] : [];
  return ids.map(id => (nodesList || []).find(n => n.id === id) || {id, name: id});
}

// What is typed and ticked, back into the draft before a redraw or a save.
function rnReachSync(){
  const ns = rnReachNodes();
  $("rnReachRows").querySelectorAll(".rnreach").forEach(row => {
    const e = rnReachDraft[+row.dataset.i];
    if (!e) return;
    e.addr = row.querySelector("[data-reach]").value.trim();
    const ticks = [...row.querySelectorAll("[data-reachnode]")];
    if (ticks.length){
      const on = ticks.filter(t => t.checked).map(t => t.value);
      e.nodes = on.length === ns.length ? [] : on;
    }
  });
}

function rnDrawReach(focus){
  if (rnMode === "git") return;
  const box = $("rnReachRows");
  if (box.childElementCount) rnReachSync();
  // Nodes Write, as the server asks (R255 step 3), not the administrator
  // role: a role of anybody's may give it.
  const ns = rnReachNodes(), ro = state?.areas ? state.areas.nodes !== "write" : !state?.admin;
  box.innerHTML = rnReachDraft.map((e, i) => `<div class="rnreach" data-i="${i}">
      <input data-reach value="${esc(e.addr)}" autocomplete="off" spellcheck="false" placeholder="192.168.1.20 or 192.168.1.20:8080"
        aria-label="an address a session here may reach"${ro ? " disabled" : ""}>
      ${ns.length > 1 ? `<span class="rnreachnodes">${ns.map(n => `<label class="ndcap"><input type="checkbox" data-reachnode value="${esc(n.id)}"${
        !e.nodes.length || e.nodes.includes(n.id) ? " checked" : ""}${ro ? " disabled" : ""}> ${esc(n.name)}</label>`).join("")}</span>` : ""}
      ${ro ? "" : rmIcon("data-reachrm", "remove this address", {title: "remove this address"})}
    </div>`).join("");
  // Empty is no box at all, so the field keeps its rhythm under the label.
  box.hidden = !rnReachDraft.length;
  $("rnReachAdd").hidden = ro;
  box.querySelectorAll("[data-reachrm]").forEach(b => b.onclick = () => {
    rnReachSync();
    rnReachDraft.splice(+b.closest(".rnreach").dataset.i, 1);
    // Read already: the rows on screen no longer line up with the draft.
    $("rnReachRows").innerHTML = "";
    rnDrawReach();
  });
  if (focus) box.querySelector(".rnreach:last-child [data-reach]")?.focus();
  // Every node keeps each session to its own project's network (R146).
  $("rnReachHint").textContent = !ns.length ? "" : "An address for the whole machine, or address:port for one service.";
}

// What Save sends: the rows with an address, in the stored shape.
function rnReachNow(){
  rnReachSync();
  return rnReachDraft.filter(e => e.addr).map(e => ({addr: e.addr, nodes: [...e.nodes].sort()}));
}

// A listbox row: a checkbox, the name, and a quiet note at the right.
const lrow = (value, name, sub, on) => `<label class="lrow"><input type="checkbox" value="${esc(value)}"${
    on ? " checked" : ""}><span>${esc(name)}</span>${sub ? `<span class="lsub">${esc(sub)}</span>` : ""}</label>`;

// The rest of the set (R82) and the hosting-only nodes (prefs.hosts) in one
// list (the operator, 13 Oct): every node but the primary, a listbox row
// each, a hosting-only one marked so in its name, ticked for the ones the
// project also works on or hosts containers on. Redrawn when the primary
// changes, since the primary is never offered twice.
function rnFillNodesMore(){
  const box = $("rnNodesMore"), hint = $("rnNodesMoreHint"), label = $("rnNodesLabel");
  if (!box) return;
  const primary = $("rnNode").value;
  const was = new Set([...rnPrefWas.nodes.split(","), ...rnPrefWas.hosts.split(",")].filter(Boolean));
  const checked = new Set([...box.querySelectorAll("input:checked")].map(i => i.value));
  const first = !box.dataset.drawn;
  // Without a primary there is nothing for a session to also work on, but
  // a hosting-only node still takes the project's containers, so those
  // rows stay on offer.
  const others = (nodesList || []).filter(n => n.kind !== "local" && n.state !== "retired" && n.state !== "disabled" && n.id !== primary
                                            && (primary || n.config?.host_only));
  // A hosting node named but gone, or no longer hosting-only, stays ticked
  // so Save does not drop it without anybody seeing.
  const gone = rnPrefWas.hosts.split(",").filter(id => id && !others.some(n => n.id === id) && id !== primary);
  box.hidden = hint.hidden = label.hidden = rnMode === "git" || !(others.length || gone.length);
  box.innerHTML = others.map(n => lrow(n.id, n.config?.host_only ? `${n.name} (Hosting only)` : n.name,
                                       `${n.config?.host_only ? "containers" : n.kind}, ${n.state}${n.live === false ? ", quiet" : ""}`,
                                       first ? was.has(n.id) : checked.has(n.id))).join("")
    + gone.map(id => lrow(id, `${id} (Hosting only)`, "not a hosting node now", first ? true : checked.has(id))).join("");
  // Read-only without the `node` grant, like the primary above (R137 step 4).
  if (state?.can?.node === false) box.querySelectorAll("input").forEach(i => { i.disabled = true; });
  // Drawn from what is saved until a draw has had nodes to draw: one made
  // before the node list arrived listed nothing, and marking it drawn made
  // the real one read its own empty boxes, so a saved second node came up
  // unticked and read as one to drop (B796, seen on dev, 16 Oct).
  if (nodesList !== null) box.dataset.drawn = "1";
  // Also reaches ticks among these, so it is drawn after them.
  rnDrawReach();
}

// The projects a session here may read: every other project this account
// sees, a listbox row each, ticked from the settings. Read-only there by
// construction (users.with_reads), so the hint under it can say so plainly.
// ---- the Toolchains group (R77) -------------------------------------------
// The toolchains installed on the project's node, as its Toolchains page
// lists them, and every tool pack: a row each, ticked when its sessions may
// use it. Fetched when the settings open; null until it has arrived.
let rnToolsList = null;
async function rnLoadTools(p){
  rnToolsList = null;
  // Not on the repository's own door (rnMode "git"), like Reads beside it.
  $("rnToolsField").hidden = rnMode === "git";
  if (rnMode === "git") return;
  $("rnTools").innerHTML = `<div class="hint">reading the toolchains on its node…</div>`;
  const node = p?.prefs?.node || "";
  const j = await (await fetch("/api/toolchains" + (node ? `?node=${encodeURIComponent(node)}` : ""))).json().catch(() => ({}));
  if (p?.name && p.name !== rnFor) return;          // another project's settings opened meanwhile
  rnToolsList = (j.items || []).filter(i => i.installed || i.pack);
  rnFillTools();
}
function rnFillTools(){
  const box = $("rnTools");
  if (!box || rnToolsList === null) return;
  const off = new Set(rnPrefWas.tc_off.split(",").filter(Boolean)), on = new Set(rnPrefWas.packs_on.split(",").filter(Boolean));
  const shipped = rnToolsList.filter(i => !i.pack).sort((a, b) => a.label.localeCompare(b.label));
  const packs = rnToolsList.filter(i => i.pack).sort((a, b) => a.label.localeCompare(b.label));
  const row = (i, attr, ticked, sub) => lrow(i.name, i.label, sub, ticked).replace("<input ", `<input ${attr} `);
  box.innerHTML = shipped.map(i => row(i, "data-shipped", !off.has(i.name), i.version || "installed"))
    .concat(packs.map(i => row(i, "data-pack", on.has(i.name),
      `tool pack, added by ${i.pack.by || "an administrator"}${i.installed ? "" : "; not installed on its node yet"}`))).join("")
    || `<div class="hint">nothing is installed on its node yet</div>`;
  box.querySelectorAll("input").forEach(i => i.onchange = () => rnBars());
}

// A list setting read off the Toolchains rows, in its saved order. A saved
// name with no row (a pack since removed, a toolchain gone from the node)
// stays as saved: the form cannot draw it, and not drawing it is no change
// (B85: the group opened marked unsaved). A drawn one stays while its row
// still says so, and one newly said goes on the end.
function rnRowsList(saved, inputs, says){
  const rows = [...inputs], drawn = new Set(rows.map(i => i.value)), now = rows.filter(says).map(i => i.value);
  const was = saved.split(",").filter(Boolean);
  return [...was.filter(n => !drawn.has(n) || now.includes(n)), ...now.filter(n => !was.includes(n))].join(",");
}

// The coding agents beside Claude a session here may run (R95), each a
// row to tick, from the agent table; ticked is allowed.
function rnFillAgents(off = rnPrefWas.agents_off, dflt = rnPrefWas.agent_default){
  const box = $("rnAgents");
  if (!box) return;
  const was = new Set(String(off || "").split(",").filter(Boolean));
  box.innerHTML = agentsLive().filter(a => a.id !== "claude")
    .map(a => lrow(a.id, a.name, a.product, !was.has(a.id))).join("");
  // Which guards hold for which agent (R95 step 6), said rather than implied.
  const g = $("rnAgentGuards");
  if (g) g.innerHTML = agentsLive().map(a => `<div><b>${esc(a.name)}</b>: ${esc(AGENT_GUARDS[a.id] || "")}</div>`).join("");
  // The one Start opens (R95 step 4): an agent left ticked, Claude first.
  const sel = $("rnAgentDefault");
  const offer = () => {
    const off2 = new Set([...box.querySelectorAll("input:not(:checked)")].map(i => i.value));
    const cur = sel.value || dflt || "claude";
    sel.innerHTML = agentsLive().filter(a => !off2.has(a.id))
      .map(a => `<option value="${esc(a.id)}"${a.id === cur ? " selected" : ""}>${esc(a.name)}</option>`).join("");
    if (!sel.value) sel.value = "claude";
  };
  if (sel){ sel.value = ""; offer(); box.querySelectorAll("input").forEach(i => i.addEventListener("change", offer)); }
  // Drawn again on a revert, after rnLockSettings ran: held the same way.
  if ((state?.projects || []).find(x => x.name === rnFor)?.may_settings === false)
    box.querySelectorAll("input").forEach(i => { i.disabled = true; i.dataset.rnlock = "1"; });
}

function rnFillReads(){
  const box = $("rnReads"), wrap = $("rnReadsField");
  if (!box) return;
  // What it reads is projects (R138): every other one, by its name, the
  // value its key, which is what a read names; a read written as one of its
  // repositories ticks it too.
  const was = new Set(rnPrefWas.reads.split(",").filter(Boolean).map(r => reposOf(r) || r));
  const own = reposOf(rnFor);
  const others = projectList().filter(c => c.key !== own).sort((a, b) => a.name.localeCompare(b.name));
  wrap.hidden = rnMode === "git" || !others.length;
  box.innerHTML = others.map(c => lrow(c.key, c.name,
    c.rows.length === 1 && c.rows[0].branch ? `git: ${c.rows[0].branch}` : c.rows.length ? `${c.rows.length} repositories` : "no repository yet",
    was.has(c.key))).join("");
  // BuilderBot's owner's alone (the operator, 6 Oct): shown to everybody,
  // changed by the owner, and why not said on the row (not a tooltip).
  const mine = state?.can?.reads !== false;
  box.querySelectorAll("input").forEach(i => { i.disabled = !mine; });
  $("rnReadsWhy").hidden = mine;
}

// How this person's terminals here look with the colors picked, their
// Profile's look and their own changes to that scheme with it.
function rnTermPreview(){
  const box = $("rnTermPreview");
  if (!box) return;
  const look = state?.term_look || {}, scheme = $("rnTermScheme").value || look.scheme || "default";
  box.innerHTML = termPreview(termPalette(scheme, (look.colors || {})[scheme]), look);
}

function rnFillPrefsRest(p){
  $("rnBuildCmd").value = p?.prefs?.build || "";
  $("rnTestCmd").value = p?.prefs?.test || "";
  // Offered only where there is a container to run in: the Docker tab knows
  // which projects have one, and `has_compose` on the project row is the
  // same answer without asking it.
  const canDevTest = !!(p?.has_compose || (p?.prefs?.tests_in || "node") !== "node");
  $("rnTestWhere").hidden = !canDevTest;
  $("rnDevTest").value = p?.prefs?.tests_in || "node";
  $("rnTestChange").value = p?.prefs?.test_change || "wait";
  $("rnGpu").value = p?.prefs?.gpu || "on";
  $("rnReply").value = p?.yours?.reply || "";
  $("rnAsks").value = p?.yours?.asks || "";
  $("rnTermScheme").value = p?.yours?.term_scheme || "";
  rnTermPreview();
  $("rnTermScheme").onchange = rnTermPreview;
  $("rnOutputs").value = (p?.prefs?.outputs || []).join(", ");
  $("rnCaptureDays").value = String(p?.prefs?.capture_days ?? 7);
  $("rnSnapDays").value = String(p?.prefs?.snapshot_days ?? 14);
  $("rnSnapOn").checked = p?.prefs?.snapshots_on !== false;
  $("rnDevKeep").value = String(p?.prefs?.dev_keep ?? 3);
  // Every dial here is a select filled once with its words and set to the
  // project's value: one helper for all of them (consistency pass), where
  // each was a copy of the same eight lines.
  const pick = (id, choices, value) => {
    const el = $(id);
    if (el.dataset.built !== "1"){
      el.innerHTML = optionList(choices);
      el.dataset.built = "1";
    }
    el.value = value;
    return el;
  };
  for (const [k, id] of Object.entries(GATE_IDS)) pick(id, gateChoices(k), p?.prefs?.gate?.[k] || "auto");
  // Auto and deny only: a report has nothing to hold for approval.
  pick("rnGateReport", GATE_MODES.filter(([v]) => v !== "ask"), p?.prefs?.report || "auto");
  pick("rnGateSign", GATE_MODES, p?.prefs?.sign || "ask");
  pick("rnGateRelease", GATE_MODES, p?.prefs?.release || "ask");
  pick("rnGateKeys", GATE_MODES, p?.prefs?.keys || "ask");
  // A lent PC (R270 step 6): deny by default, it is somebody's own machine.
  pick("rnGatePc", GATE_MODES, p?.prefs?.pc || "deny");
  pick("rnGateVersion", Object.entries(POLICY_LABEL), p?.version_policy || "locked");
  // docker-write's to change (the grant, R137 step 4), so not offered otherwise.
  pick("rnGateDocker", GATE_MODES, devClaudeMode(rnFor)).closest("label").hidden = state?.can?.["docker-write"] === false;
  // ...and its VMs' (R91), the VMs area's to change, deny unless set.
  pick("rnGateVms", GATE_MODES, p?.prefs?.makevms || "deny").closest("label").hidden = state?.can?.["vms-write"] === false;
  rnVmCapsSet(rnVmCapsOf(p));
  $("rnVmCapsRow").hidden = state?.can?.["vms-write"] === false;
  rnDrawPrefs();
}

// The project's VM limits (R91 step 7), as one string so the dirty check
// compares it as it does every other field; memory shown in GB.
function rnVmCapsOf(p){
  const c = p?.prefs?.vm_caps || {count: 4, vcpus: 8, mem_mb: 16384, disk_gb: 200};
  return JSON.stringify({count: c.count, vcpus: c.vcpus, mem_mb: c.mem_mb, disk_gb: c.disk_gb});
}
function rnVmCapsNow(){
  const n = id => Math.max(0, Math.round(+$(id).value || 0));
  return JSON.stringify({count: n("rnVmCount"), vcpus: n("rnVmCpus"), mem_mb: n("rnVmMem") * 1024, disk_gb: n("rnVmDisk")});
}
function rnVmCapsSet(s){
  const c = JSON.parse(s || "{}");
  $("rnVmCount").value = c.count ?? 4; $("rnVmCpus").value = c.vcpus ?? 8;
  $("rnVmMem").value = Math.round((c.mem_mb ?? 16384) / 1024); $("rnVmDisk").value = c.disk_gb ?? 200;
}

function rnDrawPrefs(){
  const p = (state?.projects || []).find(x => x.name === rnFor);
  // Ghosted where no session can start: a project locked against this
  // account (R119). The model and effort are not here any more: a session
  // starts on the ones picked in the agent's menu each time (the operator,
  // 12 Oct).
  const shut = !!p?.locked_me;
  $("rnReply").disabled = $("rnAsks").disabled = $("rnTermScheme").disabled = shut;
  $("rnPrefHint").textContent = shut
    ? lockedWhy(p) + "."
    : "Applied the next time Claude starts here. The model and effort are picked each time a session starts, in the Claude button's menu.";
}

// ---- a project's settings dialog, wired ---------------------------------

// Unlinking asks, and the question lists what goes rather than asking twice:
// a stored token is not recoverable and a push grant frees the repository for
// another project. Nothing in the tree is touched, which is the half worth
// saying out loud; somebody pressing this is worried about their commits.
async function unlinkProject(name){
  const p = (state?.projects || []).find(x => x.name === name);
  const where = p?.forge_host || p?.forge_name || "its remote";
  if (!await askYes(`Unlink ${projLabel(name)} from ${where}?\n\n`
      + `The remote and its stored token go; every commit and branch stays. `
      + `You can link it elsewhere afterwards.`)) return;
  const stop = m => { $("rnErr").textContent = m; $("rnErrWrap").hidden = false;
                      unbusy($("rnUnlink"), `Unlink from ${p?.forge_name || "its remote"}`); };
  busy($("rnUnlink"), "Unlinking");
  try{
    const r = await postJSON("/api/unlink", {name});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) return stop(j.error || `unlink failed (HTTP ${r.status})`);
    closeRename();
    notify(`${projLabel(name)} is unlinked: ${(j.removed || []).join(", ")}`
           + (j.others?.length ? `. Its other remotes are untouched: ${j.others.join(", ")}` : ""));
  }catch(e){ return stop("unlink failed: " + e); }
  refresh();
}

// ---- a project's settings dialog: open, drawn and sent ------------------

// Renaming asks, because it moves a directory and a dozen keyed stores with
// it, and because the answer it gives back is worth reading: what moved, and
// anything that did not. A rename that half-worked is the case this reports
// rather than hides: the alternative is a project whose roadmap silently
// stayed behind under a name nothing points at any more.
let rnFor = null;                        // the project the dialog is open on
let rnMode = "all";                      // "all" from the gear, "git" from the chain
let rnOpens = 0;                         // which opening of the dialog this is

// The form shown in a notebook's Settings view instead of the dialog (R119
// step 3): one form, moved to where it is wanted. `rnHost` is the view's
// .modal.inline while the form is there, else null and the form is the
// dialog's.
let rnHost = null;
function settingsOut(){
  if (!rnHost) return;
  const box = rnHost.querySelector(":scope > .box");
  splitOff(box);
  if (box) $("rnmodal").appendChild(box);
  rnHost = null;
  $("rnCancel").hidden = false;
}
function settingsInto(name, host){
  if (!host) return;
  // Already here for this project: nothing to move, and redoing it would
  // put every field back and hide People until its read lands again (the
  // operator, 16 Oct: People there one time and not the next).
  if (rnHost === host && rnFor === name && host.querySelector(":scope > .box")){
    // ...but what others may have changed is read again, in place: the
    // days kept, who is on it, the sessions running.
    rnLoadSnapshots(name, true);
    rnLoadPeople(name, true);
    if (typeof rnSessionsLoad === "function") rnSessionsLoad(name);
    return;
  }
  // Lent to another view still: taken back first, so the form is the
  // dialog's again before it moves here.
  if (rnHost && rnHost !== host) settingsOut();
  renameProject(name);
  $("rnmodal").hidden = true;
  const box = $("rnmodal").querySelector(":scope > .box");
  // The scroll hints mark a dialog's box that can scroll, and the class
  // came along with the box into the view, where nothing scrolls and the
  // hint's rule re-drew the dialog's drop shadow around the form (B702).
  if (box) box.classList.remove("scrollup", "scrolldown");
  if (box) host.appendChild(box);
  // A view, never a dialog to shut: whatever hid it is undone here.
  host.removeAttribute("hidden");
  rnHost = host;
  // In place there is nothing to close: each section's Revert puts its
  // fields back.
  $("rnCancel").hidden = true;
  // On a phone it opens on the list.
  if (box){ (SPLIT["rn:" + name] || (SPLIT["rn:" + name] = {pick: "", open: false})).open = false; rnSplit(box, name); }
}

// ---- the Settings view: the sections as a list beside the one picked ----
// The operator, 16 Oct: twelve sections open one under another were hard to
// find a setting in. In the notebook they are a page of settings
// (page-docs.js splitSects): a list of them, each with what is in it,
// beside the one picked; on a phone the list, then the section with Back.
// The dialog (the Git view's remote door) keeps them open under a jump bar.
const RN_LIST = {
  project: "the name it is shown under", people: "owner, who is on it, invitations",
  claude: "what its sessions do on their own, ask about, or may not",
  yours: "your replies, questions and commit name here",
  repo: "how it pushes and pulls", runs: "where it builds, tests and runs",
  build: "commands, outputs, and what is kept", sees: "other projects, shares, addresses",
  tools: "the toolchains and tool packs its sessions use",
  files: "its files over FTP and in an editor", snapshots: "the days kept, and putting one back",
  sessions: "every account's sessions here, to end",
};

function rnSplit(box, name){
  // Agents may is the Permissions view's (the operator, 22 Oct), and not
  // listed here; the dialog still carries it under its jump bar.
  splitSects(box, "rn:" + name, {says: RN_LIST, sel: ':scope > details.rngroup:not([data-sect="rn:claude"])', back: "Settings",
    marks: k => RN_SECTS.includes(k) && rnSectChanges(k).said.length > 0});
}
// A project's settings: its notebook's Settings view, at one of its sections
// when `sect` names it (a node's Projects section opens Where it runs).
function openProjectSettings(name, sect = ""){
  if (sect) SPLIT["rn:" + name] = {pick: sect, open: true};
  openNotebook(name, "settings");
}

// The Agents may section, lent to a notebook's Permissions view
// (nb-permissions.js), goes back to its place in the form, marked by this
// comment, before the form is used anywhere else.
const RN_DIALS_MARK = "rn:claude lent to Permissions";
function rnDialsHome(){
  const box = $("rnmodal").querySelector(":scope > .box") || rnHost?.querySelector(":scope > .box");
  const at = box && [...box.childNodes].find(n => n.nodeType === Node.COMMENT_NODE && n.data === RN_DIALS_MARK);
  if (!at) return;
  const sect = [...document.querySelectorAll('details[data-sect="rn:claude"]')].find(d => !d.closest(".fghost"));
  if (sect) at.parentNode.insertBefore(sect, at);
  at.remove();
}

function renameProject(name, mode = "all"){
  rnDialsHome();
  settingsOut();
  rnFor = name;
  rnMode = mode;
  rnOpens++;
  const p = (state?.projects || []).find(x => x.name === name);
  // One dialog, two doors. The gear is the project's own settings; the chain
  // is the remote's half of them, and opening it there hides everything that
  // is not about the remote rather than scrolling past it.
  const git = mode === "git";
  // Named rather than assumed: a project on somebody's own Gitea should not
  // read "GitHub settings", and the host is the one fact this door is about.
  const where = p?.forge_name || "its remote";
  $("rnTitle").textContent = git ? `${where} settings for ${projLabel(name)}` : projLabel(name);
  for (const id of ["rnNameField", "rnMineField",
                    "rnGateField", "rnBuildField", "rnReadsField", "rnAgentsField"])
    $(id).hidden = git;
  // The node picker and the two credential blocks have hidden rules of their
  // own further down, and each of those consults the mode too.
  $("rnName").value = projLabel(name);
  $("rnToken").value = "";
  $("rnErrWrap").hidden = true;
  $("rnPreview").hidden = true;
  $("rnName").classList.remove("bad");
  // Where the project is on disk and its id (R154), said from the start.
  $("rnHint").textContent = rnFolderLine(name);
  // Offered where a token would mean something: a project that already has
  // one, and a project that may push but pushes with a deploy key; that
  // second case is the way off deploy keys, and without it there was no way
  // to give such a project a token at all.
  //
  // Still hidden for a read-only clone and for a local repo: a credential
  // there has nothing to authenticate against, and offering one would imply
  // it grants something. Push rights are granted once, at clone.
  const how = p?.push_how || "";
  $("rnTokenField").hidden = git ? !(p?.has_token || p?.push) : true;
  // The deploy-key case is tested FIRST and stays true after a token is set:
  // storing one does not change what git uses (git never asks a credential
  // helper about an ssh remote), and a hint that stopped saying so the moment
  // a token existed would be wrong exactly when it mattered. One line each,
  // per the site-text rule: the reasoning lives here and in the README.
  $("rnTokenHint").textContent = how === "key"
    ? p?.has_token
      ? "This project pushes with a deploy key and already has a token stored; "
        + "the switch below decides which git uses."
      : "This project pushes with a deploy key, so a token here does nothing "
        + "until the switch below says to use it."
    : p?.has_token
      ? "Replaces this project's token. Kept for it alone; a shell here can read it."
      : "Kept for this repository alone; a shell here can read it.";
  // Nothing to set is an answer, not an empty box: a linked project with no
  // token and no push rights has a remote it can only read.
  $("rnGitNone").hidden = !(git && $("rnTokenField").hidden);
  if (!$("rnGitNone").hidden)
    $("rnGitNone").firstElementChild.textContent =
      `${projLabel(name)} has a remote it can only read, so there is no credential to set here.`;
  // The Settings view keeps the credential fields behind the remote's door,
  // which left its Repository section listed and empty (B813): it says what
  // the remote is and how it pushes here, and opens the door.
  const sum = $("rnRepoSum");
  sum.hidden = git || !p?.git_ok;
  if (!sum.hidden){
    const host = p.linked ? `${p.forge_name || "its host"}${p.forge_host ? ` (${p.forge_host})` : ""}` : "";
    const with_ = how === "key" ? "a deploy key" : p.has_token ? "a token" : "its stored credential";
    $("rnRepoSay").textContent = !p.linked ? `${projLabel(name)} is linked to no git host yet.`
      : `Linked to ${host}; it ${p.push ? `pushes with ${with_}` : "can only read the remote"}.`;
    const go = $("rnRepoGo");
    go.textContent = p.linked ? `${p.forge_name || "Remote"} settings` : "Link to a git host";
    go.disabled = state?.can?.["git-auth"] === false;
    go.onclick = () => { if (p.linked) renameProject(name, "git"); else openLinkProject(name); };
  }
  // Unlink is the chain's, never the gear's: it is about the remote, and it
  // is the way a project moves from one host to another, since linking
  // refuses a repo that already has one.
  $("rnUnlink").hidden = !(git && p?.linked);
  unbusy($("rnUnlink"), `Unlink from ${p?.forge_name || "its remote"}`);
  // The bin, on the gear's door only: the chain's is about the remote.
  // Not drawn for a role that does not give it (the operator, 21 Oct).
  $("rnDelete").hidden = git || !p || !!p?.trash_why;
  $("rnKeyOut").hidden = true; $("rnKeyPaste").hidden = true; $("rnKeyPaste").value = "";
  rnLoadAuth(name);
  rnLoadSnapshots(name);
  rnLoadPeople(name);
  rnLoadFtp(name);
  rnFillPrefs(p);
  // The sessions at the foot: the gear's door, and an administrator's.
  $("rnSessField").hidden = true;
  // Asked of the server, which answers by the account's areas on this
  // project (R255 steps 3 and 4), and its refusal said under the section.
  if (!git) rnSessionsLoad(name);
  $("rnmodal").hidden = false;
  rnFolds();
  // Each section's Save and Revert, drawn dead until something changes.
  document.querySelectorAll(".rnbar .state.bad").forEach(x => { x.classList.remove("bad"); x.textContent = ""; });
  rnBars();
}

// Sections, every one open unless this person shut it here (the operator,
// 8 Oct: too much was hidden in folds), with the jump bar over them.
function rnFolds(){
  const all = [...document.querySelectorAll("details.rngroup")];
  // Moved by a door, not by a hand: the press mark comes off first, so the
  // toggle this fires does not record a fold shut as this person shutting it.
  for (const d of all){
    const want = sectOpen[d.dataset.sect] !== false;
    if (d.open === want) continue;
    delete d.dataset.pressed;
    d.open = want;
  }
  const box = document.querySelector("#rnmodal [data-sects]");
  if (box) sectJump(box);
}

// What the remote uses now, and what the operator has picked instead. Both
// null until this open's /api/project-auth answers: the dialog draws without
// them rather than waiting, so the token field is typeable before the request
// lands and the switch appears under it when it does.
// ---- people (membership.py) ----
// The project's owner, whether it is invite only, who is on it and who is
// invited. The owner and the restriction are a draft until Save; Invite and
// Withdraw act on the press, as the actions they are.
let rnPeople = null, rnPeopleDraft = {};

// The Git view's session dials, read here with the rest of what a session
// may do and set on the Git view (R255 step 7).
function rnDrawGitPol(name){
  // A project on the defaults carries no gitpol: read as the Git view does.
  const pol = (state?.projects || []).find(p => p.name === name)?.prefs?.gitpol || {};
  setHidden($("rnGitPolField"), rnMode === "git");
  setText($("rnGitPol"), `its branches ${pol.push || "allow"} · to main ${pol.main || "deny"} · a sensitive push ${
    (pol.scan || "hold") === "hold" ? "held for you" : "not held"}`);
  $("rnGitPolGo").onclick = () => { closeRename(); openNotebook(name, "git"); };
}

// `keep`: read again in place, and drawn only when nothing there is being
// changed, so a staged owner or Invite only is not put back under the hand.
function rnLoadPeople(name, keep = false){
  if (!keep){
    rnPeople = null; rnPeopleDraft = {};
    $("rnPeopleField").hidden = true;
    setHidden($("rnPeopleField").closest("details"), true);
  }
  rnDrawGitPol(name);
  if (rnMode === "git") return;
  postJSON("/api/members", {action: "view", project: name})
    .then(r => r.json())
    .then(j => { if (rnFor !== name || j.error) return;
                 if (keep && Object.keys(rnPeopleDraft).length) return;
                 rnPeople = j; rnDrawPeople(); })
    .catch(() => {});
}

function rnDrawPeople(){
  // The chain's door is the remote's alone, and a load the gear's door
  // started can land after it opens (B539).
  if (!rnPeople || rnMode === "git") return;
  const v = rnPeople, d = rnPeopleDraft;
  const owner = d.owner ?? v.owner, only = d.invite_only ?? v.invite_only;
  const invitable = v.accounts.filter(n => !v.members.includes(n) && !v.invites.some(i => i.name === n));
  $("rnPeopleField").hidden = false;
  setHidden($("rnPeopleField").closest("details"), false);
  $("rnPeople").innerHTML = `
    <div class="setrow ctlrow">${v.may_manage
      ? `<label class="ndcap" for="rnOwner">Project owner</label>
         <select id="rnOwner">${optionList(v.accounts, owner)}</select>`
      : `<span>Project owner: ${esc(v.owner || "BuilderBot's owner")}</span>`}</div>
    ${v.may_manage && !v.bb_owner && d.owner && d.owner !== v.owner
      ? `<div class="sub">Saving offers it to ${esc(d.owner)}, who becomes its owner on accepting from their bell.</div>` : ""}
    ${v.offer ? `<div class="rninvite">Ownership offered to ${esc(v.offer.name)} <span class="dim">${esc(ago(v.offer.at))}, waiting for them to accept</span>
      ${v.may_manage ? `<button type="button" class="link" data-withdraw="${v.offer.id}">Withdraw</button>` : ""}</div>` : ""}
    <label class="ndcap"><input type="checkbox" id="rnInviteOnly"${only ? " checked" : ""}${v.may_manage ? "" : " disabled"}>
      Invite only</label>
    <div class="sub whoson">On it: ${v.members.length ? v.members.map(n => v.may_manage
      ? `<button type="button" class="namelink" data-rnaccess="${esc(n)}" title="what ${esc(n)} holds here and everywhere">${esc(n)}</button>`
      : esc(n)).join(", ") : "nobody yet"}</div>
    ${v.invites.map(i => `<div class="rninvite">${esc(i.name)} <span class="dim">invited${i.role ? ` as ${esc(i.role)}` : ""} by ${esc(i.by || "somebody")} ${esc(ago(i.at))}</span>
      <button type="button" class="link" data-withdraw="${i.id}">Withdraw</button></div>`).join("")}
    ${v.may_invite && invitable.length ? (v.roles || []).length ? `<div class="rninvitebar">
      <select id="rnInviteWho" aria-label="account to invite">${invitable.map(n => `<option>${esc(n)}</option>`).join("")}</select>
      <select id="rnInviteRole" aria-label="the role they are invited as">${v.roles.map(n => `<option>${esc(n)}</option>`).join("")}</select>
      <button type="button" id="rnInviteGo">Invite</button></div>`
      : `<div class="sub warn">no role on this project to invite anybody with: add one on the ${pageLink("roles", "Roles page")}</div>` : ""}`;
  const o = $("rnOwner");
  if (o) o.onchange = () => { d.owner = o.value; rnDrawPeople(); };
  // What each person holds (R152): a name opens their roles, which a
  // project's owner gives on the projects they own (the operator, 17 Oct:
  // the Roles page lists roles alone).
  const pn = rnFor;
  $("rnPeople").querySelectorAll("[data-rnaccess]").forEach(x => x.onclick = () =>
    rolesAccessOpen(x.dataset.rnaccess, () => rnLoadPeople(pn, true)));
  const io = $("rnInviteOnly");
  if (io && v.may_manage) io.onchange = () => { d.invite_only = io.checked; rnDrawPeople(); };
  const act = async body => {
    const j = await (await postJSON("/api/members", body)).json();
    if (j.error) return notify(j.error, true);
    rnPeople = j; rnDrawPeople();
  };
  const go = $("rnInviteGo");
  if (go) go.onclick = () => act({action: "invite", project: rnFor, name: $("rnInviteWho").value,
                                   role: $("rnInviteRole").value})
    .then(() => notify(`invited to ${projLabel(rnFor)}: they say yes or no from their bell`));
  $("rnPeople").querySelectorAll("[data-withdraw]").forEach(b =>
    b.onclick = () => act({action: "withdraw", id: Number(b.dataset.withdraw)}));
}

// The staged owner and restriction, sent by Save; "" when they landed.
async function rnSavePeople(name){
  const d = rnPeopleDraft, v = rnPeople;
  if (!v) return "";
  const owner = d.owner && d.owner !== v.owner ? d.owner : "";
  const only = d.invite_only !== undefined && d.invite_only !== v.invite_only ? d.invite_only : undefined;
  if (!owner && only === undefined) return "";
  const j = await (await postJSON("/api/members", {action: "set", project: name, owner,
                                                   ...(only !== undefined ? {invite_only: only} : {})})).json();
  if (j.offered) notify(`${projLabel(name)}: offered to ${j.offered}, who becomes its owner on accepting from their bell`);
  return j.error || "";
}

// ---- file access over FTP (R151) and in an editor (R159) ----
// The project's tree over FTPS on its node, and in a person's editor through
// the controller (BuilderBot for VS Code), each its own switch, for the
// accounts given read or read and write (ftp.py). Who may set it is the ftp
// grant; anybody else is shown what is on and where. The switches, the port
// and each account's access are a draft until Save.
const RN_FTP_ACCESS = [["", "No access"], ["r", "Read"], ["rw", "Read and write"]];
let rnFtp = null, rnFtpDraft = {};

function rnLoadFtp(name){
  rnFtp = null; rnFtpDraft = {};
  $("rnFtpField").hidden = true;
  if (rnMode === "git") return;
  postJSON("/api/project-ftp", {project: name})
    .then(r => r.json())
    .then(j => { if (rnFor !== name || j.error) return; rnFtp = j; rnDrawFtp(); })
    .catch(() => {});
}

function rnFtpWhere(v){
  const st = v.status || {};
  return st.addr && st.port ? `${st.addr}:${st.port}` : "";
}

function rnDrawFtp(){
  if (!rnFtp || rnMode === "git") return;
  const v = rnFtp, d = rnFtpDraft;
  const on = d.on ?? v.on, editor = d.editor ?? v.editor, st = v.status || {}, where = rnFtpWhere(v);
  const box = $("rnFtp");
  // Switched off on this install (R81): the sentence, and nothing to set.
  if (featureOff("ftp")){
    $("rnFtpField").hidden = false;
    box.innerHTML = deadWhy(featureOff("ftp"));
    return;
  }
  if (!v.may_set){
    $("rnFtpField").hidden = !v.on && !v.editor;
    box.innerHTML = `${v.on ? `<div>Served over FTPS${where ? `, at ${esc(where)}` : ""}.</div>` : ""}
      ${v.editor ? `<div>Open from your own machine: BuilderBot for VS Code and the Windows companion.</div>` : ""}
      <div class="hint">Sign in with your BuilderBot name and password, if you were given access.
        Who may is set by BuilderBot's owner, or a role that grants ftp.</div>`;
    return;
  }
  $("rnFtpField").hidden = false;
  const port = d.port ?? v.port;
  // Said as soon as it is ticked, before anything is tried (the operator, 7 Oct).
  const status = on && !v.on && v.missing ? `<div class="hint bad">${esc(v.missing)}</div>`
    : !v.on ? ""
    : st.up ? `<div class="hint">Running at ${esc(where)}. Use FTPS (FTP over explicit TLS, not SFTP) and
        your BuilderBot name and password. The certificate is the node's own, so the client asks to trust it once.</div>`
    : st.why ? `<div class="hint bad">Not running: ${esc(st.why)}</div>`
    : `<div class="hint">Starting on its node.</div>`;
  box.innerHTML = `
    <label class="ndcap"><input type="checkbox" id="rnFtpOn"${on ? " checked" : ""}> Serve this project's files over FTPS</label>
    <label class="ndcap"><input type="checkbox" id="rnFtpEditor"${editor ? " checked" : ""}> Open them from people's own machines: BuilderBot for VS Code and the Windows companion</label>
    ${editor ? `<div class="hint">Through this controller, as each person's own account: everyone on the project gets what their roles' File access gives, and a choice on the list below narrows it.</div>` : ""}
    ${v.node || !on ? "" : `<div class="hint bad">It has no node to run on: pick one under Nodes.</div>`}
    <div class="logdays setrow ctlrow"${on ? "" : " hidden"}><label class="ndcap" for="rnFtpPort">Port<span class="help" data-help="the port and the ${v.span - 1} after it, which carry the data; projects on one node are kept ${v.span} ports apart" tabindex="0">?</span></label>
      <input id="rnFtpPort" type="number" min="1024" max="65526" step="1" inputmode="numeric" value="${esc(String(port))}" aria-label="the port its FTP server listens on">
      <span class="dim">and the ${v.span - 1} after it</span></div>
    ${status}
    <div class="rnftppeople"${on || editor ? "" : " hidden"}>${v.people.map(p => {
      const a = d.access?.[p.uid] ?? p.access;
      return `<div class="rnftprow"><span class="grow">${esc(p.name)}</span>
        <select data-ftpuid="${esc(p.uid)}" aria-label="${esc(p.name)}'s file access">${optionList(RN_FTP_ACCESS, a)}</select></div>`;
    }).join("")}</div>`;
  $("rnFtpOn").onchange = e => { d.on = e.target.checked; rnDrawFtp(); };
  $("rnFtpEditor").onchange = e => { d.editor = e.target.checked; rnDrawFtp(); };
  const pi = $("rnFtpPort");
  if (pi) pi.oninput = () => { d.port = pi.value.trim(); };
  box.querySelectorAll("[data-ftpuid]").forEach(sel => sel.onchange = () => {
    d.access = {...(d.access || {}), [sel.dataset.ftpuid]: sel.value};
  });
}

// What the draft changes, or null when nothing.
function rnFtpChange(){
  if (!rnFtp?.may_set) return null;
  const d = rnFtpDraft, v = rnFtp, out = {};
  if (d.on !== undefined && d.on !== v.on) out.on = d.on;
  if (d.editor !== undefined && d.editor !== v.editor) out.editor = d.editor;
  if (d.port !== undefined && String(d.port) !== String(v.port)) out.port = d.port;
  // A port shown for a project turned on now is its offer, and is sent.
  if (out.on && out.port === undefined) out.port = v.port;
  const acc = Object.fromEntries(Object.entries(d.access || {})
    .filter(([uid, a]) => a !== (v.people.find(p => p.uid === uid)?.access ?? "")));
  if (Object.keys(acc).length) out.access = acc;
  return Object.keys(out).length ? out : null;
}

async function rnSaveFtp(name, change){
  const j = await (await postJSON("/api/project-ftp", {action: "set", project: name, ...change})).json();
  return j.error || "";
}

// ---- what this account may not do here ----
// Why this account may not read or change the project's settings, sessions
// and snapshots, from its row, or "" (B89).
const rnSettingsWhy = name => (state?.projects || []).find(p => p.name === name)?.settings_why || "";
// A section this account may not use, shown with why under it in red, the
// server's own words naming the area and level that would open it (R255
// step 4), not hidden as if there were nothing there.
function rnWhyOff(field, body, why){
  body.innerHTML = `<div class="sub bad">${esc(why)}</div>`;
  field.hidden = false;
}

// The project's daily snapshots (R165): each day kept, with Restore for the
// whole tree and a box to restore one file. An administrator's, and acted on
// at the press after a confirmation, not staged with Save: a restore is the
// thing done when something went wrong, and it first snapshots the tree as
// it is, so the line it leaves says how to undo it.
let rnSnap = null;

// `keep`: read again in place, the section left as it is until the answer.
function rnLoadSnapshots(name, keep = false){
  if (!keep){ rnSnap = null; $("rnSnapField").hidden = true; }
  if (rnMode === "git") return;
  // Not asked for where the row already says it would be refused (B89), and
  // not drawn: what a role does not give is not shown (the operator, 21 Oct).
  if (rnSettingsWhy(name)) return;
  fetch("/api/snapshots?project=" + encodeURIComponent(name))
    .then(r => r.json())
    .then(j => {
      if (rnFor !== name) return;
      if (j.error){ rnWhyOff($("rnSnapField"), $("rnSnapRows"), j.error); return; }
      rnSnap = j; rnDrawSnapshots();
    })
    .catch(() => {});
}

function rnDrawSnapshots(){
  if (!rnSnap) return;
  const name = rnFor;
  $("rnSnapField").hidden = false;
  const days = rnSnap.days || [];
  const when = d => d.at ? new Date(d.at * 1000).toLocaleString([], {dateStyle: "medium", timeStyle: "short"}) : d.day;
  $("rnSnapRows").innerHTML = (days.length ? days.map(d => `<div class="rnsnap actbar" data-day="${esc(d.day)}">
      <span class="grow">${esc(when(d))}${d.pinned ? ` <span class="pill note" title="kept whatever the days kept say">pinned</span>` : ""}${d.why ? ` <span class="dim">(${esc(d.why.replace(/-/g, " "))})</span>` : ""}
        <span class="dim">· ${d.files} files · ${esc(humanBytes(d.bytes))}</span></span>
      <input type="text" data-snapfile placeholder="a file, from the tree's top" spellcheck="false" autocomplete="off"
             aria-label="the file to restore from this day">
      <button type="button" data-snapone disabled>Restore file</button>
      <button type="button" data-snapall>Restore all</button>
      <button type="button" data-snappin="${d.pinned ? "unpin" : "pin"}" title="${d.pinned ? "let it go with the rest when it is older than the days kept" : "keep this day whatever the days kept say"}">${d.pinned ? "Unpin" : "Pin"}</button>
    </div>`).join("")
    : `<div class="dim">none yet: the first is taken within half an hour of the setting being above 0</div>`)
    + `<div class="actbar"><button type="button" data-snaptake>Take one now</button></div>`;
  const pinned = days.filter(d => d.pinned).length;
  $("rnSnapHint").textContent = (rnSnap.on === false
    ? "Daily snapshots are off, so none are taken; the ones here go as they pass the days kept."
    : rnSnap.keep
    ? `One a day, kept ${rnSnap.keep} day${rnSnap.keep === 1 ? "" : "s"}. A restore snapshots the tree first, so it can be undone from the line it leaves.`
    : "Snapshots kept is 0, so none are taken; the ones here go at the next daily look.")
    + (pinned ? ` ${pinned} pinned, kept until unpinned.` : "");
  const act = async (b, body, ask) => {
    if (ask && !await askYes(ask)) return;
    await pressing(b, async () => {
      const r = await postJSON("/api/snapshots", {project: name, ...body});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      notify(body.action === "take" ? `snapshot taken: ${j.files} files`
        : body.action === "pin" ? `${j.day} pinned: kept until unpinned`
        : body.action === "unpin" ? `${j.day} unpinned: it goes with the rest when it is old enough`
        : `restored: ${j.wrote} written, ${j.removed} removed; undo from ${j.undo}`);
      rnLoadSnapshots(name);
    });
  };
  $("rnSnapRows").querySelectorAll(".rnsnap").forEach(row => {
    const day = row.dataset.day;
    row.querySelector("[data-snapall]").onclick = e => act(e.target, {action: "restore", day},
      `Put all of ${name} back as it was on ${day}?\n\nFiles changed since are written back and files added since are removed, on the controller and then every node. The tree as it is now is snapshotted first.`);
    const pin = row.querySelector("[data-snappin]");
    pin.onclick = e => act(e.target, {action: pin.dataset.snappin, day}, "");
    // Restore file wakes once a file is typed (the operator, 18 Oct).
    const one = row.querySelector("[data-snapone]"), file = row.querySelector("[data-snapfile]");
    file.oninput = () => { one.disabled = !file.value.trim(); };
    one.onclick = e => {
      const path = row.querySelector("[data-snapfile]").value.trim();
      if (!path) return notify("type the file to restore, from the tree's top", true);
      act(e.target, {action: "restore", day, path}, `Put ${path} back as it was on ${day}?`);
    };
  });
  const take = $("rnSnapRows").querySelector("[data-snaptake]");
  if (take) take.onclick = e => act(e.target, {action: "take"}, "");
}

let rnAuthNow = null, rnAuthPick = null, rnAuthOpts = null;
// Staged, like the name and the token: pressing Clear changes what the dialog
// says and nothing on disk. Rename is the only verb here that touches the
// project, which is what makes Cancel mean something.
let rnClearToken = false;

// Fetched per open, like the new-project dialog's keys: a project's remote can
// be rewritten from a terminal between two opens, and a cached answer here
// would offer to switch to the side it is already on. Only from the chain: the
// gear no longer shows either credential control, so asking would be a request
// per settings open for an answer nothing reads.
function rnLoadAuth(name){
  rnAuthNow = rnAuthPick = rnAuthOpts = null;
  rnClearToken = false;
  $("rnAuthField").hidden = true;
  $("rnKeyField").hidden = true;
  $("rnAddrField").hidden = true;
  $("rnAddr").value = "";
  $("rnTestField").hidden = true;
  $("rnTestOut").hidden = true;
  if (rnMode !== "git") return;
  fetch("/api/project-auth", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({name})})
    .then(r => r.json())
    .then(j => {
      if (rnFor !== name || j.error) return;   // closed, or reopened elsewhere
      rnAuthOpts = j;
      rnAuthNow = rnAuthPick = j.now || null;
      // Any project with a remote, a read-only clone included: its owner can
      // be renamed too, and it has nothing else here to save.
      $("rnAddr").value = j.url || "";
      $("rnAddrField").hidden = !j.url;
      $("rnTestField").hidden = !j.url;
      rnDrawAuth();
      rnDrawKey();
      rnDrawStore(name);
      rnBars();
    })
    .catch(() => {});                          // the rename itself still works
}

// The project's own deploy key (the operator, 12 Oct): made or pasted here,
// shown by its public half with where the host takes it, forgotten here.
// Shown wherever the token is: a project that may push.
// The person's own key store, for this remote's host (R154): a token they
// gave another repository can be this one's too, and the project says whose
// store its token is in. Acts at the press.
function rnDrawStore(name){
  const box = $("rnStore");
  if (!box) return;
  const o = rnAuthOpts || {};
  let host = "";
  try{ host = new URL(String(o.url || "").replace(/^git@([^:]+):/, "https://$1/")).host.toLowerCase(); }catch(e){ host = ""; }
  const mine = (o.store || []).filter(f => f.host === host);
  // Who has given the project a token (R159): each a person, their token
  // used for their own work while they are signed in; yours removable.
  const givers = o.givers || [], me = givers.find(g => g.mine);
  const who = givers.map(g => `<div class="setrow ctlrow"><span class="grow">${g.mine ? "Your" : esc(g.name) + "'s"} ${
    esc(g.host || host)} token${g.login ? `, as ${esc(g.login)}` : ""}${g.live ? "" : `<span class="dim"> (signed out: not in use)</span>`}</span>${
    g.mine ? `<button type="button" data-rnunlink="1">Take it back</button>` : ""}</div>`).join("");
  const said = givers.length
    ? `<div class="hint">${givers.length === 1 ? "One person has" : givers.length + " people have"} given this project a token; each is used for their own pushes and pulls while they are signed in${
        me ? "" : ", and yours is not among them"}.</div>`
    : `<div class="hint">Nobody has given this project a token: pushes and pulls wait until somebody does.</div>`;
  const rows = mine.filter(f => !(me && me.id === f.id)).map(f => `<div class="setrow ctlrow"><span class="grow">Your ${
    esc(f.host)} token${f.login ? `, as ${esc(f.login)}` : ""}</span>
    <button type="button" data-rnstore="${esc(f.id)}">${me ? "Use this one instead" : "Give it to this project"}</button></div>`).join("");
  box.innerHTML = said + who + rows;
  box.hidden = !(said || who || rows);
  box.querySelectorAll("[data-rnstore]").forEach(b => b.onclick = async () => {
    busy(b, "Linking");
    try{
      const j = await (await postJSON("/api/rename", {name, link_account: b.dataset.rnstore})).json();
      if (j.error) notify(j.error, true);
      else notify(`${projLabel(name)} uses your token for your pushes and pulls`);
    }catch(e){ notify("link: " + failWords(e), true); }
    rnLoadAuth(name);
  });
  box.querySelectorAll("[data-rnunlink]").forEach(b => b.onclick = async () => {
    busy(b, "Taking back");
    try{
      const j = await (await postJSON("/api/rename", {name, unlink_mine: true})).json();
      if (j.error) notify(j.error, true);
      else notify(`your token is no longer given to ${projLabel(name)}`);
    }catch(e){ notify("take back: " + failWords(e), true); }
    rnLoadAuth(name);
  });
}

function rnDrawKey(){
  const f = $("rnKeyField");
  if (!rnAuthOpts || $("rnTokenField").hidden){ f.hidden = true; return; }
  f.hidden = false;
  const k = rnAuthOpts.deploy, pasting = !$("rnKeyPaste").hidden;
  $("rnKeyPub").hidden = !k;
  $("rnKeyPub").textContent = k ? k.pub : "";
  $("rnKeyMake").hidden = !!k || pasting;
  $("rnKeyPasteBtn").hidden = !!k;
  $("rnKeyPasteBtn").textContent = pasting ? "Keep it" : "Paste a key";
  $("rnKeyCopy").hidden = $("rnKeyForget").hidden = !k;
  $("rnKeyHint").innerHTML = k
    ? `Add this on the host as a deploy key with write access${k.page ? `: <a href="${esc(k.page)}" target="_blank" rel="noopener">its deploy keys page</a>` : ""}, then pick Deploy key below and Save.`
    : pasting ? "Paste the whole private key, without a passphrase. It is kept where sessions can push with it and never read it."
    : "None made here. Make one, or paste one you have.";
}

async function rnKeyAct(action){
  const name = rnFor, btn = {"key-make": "rnKeyMake", "key-store": "rnKeyPasteBtn", "key-forget": "rnKeyForget"}[action];
  busy($(btn), action === "key-forget" ? "Forgetting" : action === "key-make" ? "Making" : "Keeping");
  let j;
  try{
    j = await (await postJSON("/api/project-auth", {name, action,
      key: action === "key-store" ? $("rnKeyPaste").value : ""})).json();
  }catch{ j = {error: "no answer from the dashboard"}; }
  $(btn).disabled = false;
  $(btn).removeAttribute("aria-busy");
  if (rnFor !== name) return;
  const out = $("rnKeyOut");
  out.classList.toggle("bad", !!j.error);
  out.textContent = j.error || j.message || "";
  out.hidden = !out.textContent;
  if (!j.error){
    $("rnKeyPaste").value = "";
    $("rnKeyPaste").hidden = true;
    rnLoadAuth(name);
  } else rnDrawKey();
}

function rnDrawAuth(){
  // Gated on the token field as well as on having a remote: where a token
  // would mean nothing (a read-only clone, a local repo) the field above is
  // hidden, and a switch offering to use a credential the dialog will not let
  // you set is a dead end wearing a control's clothes.
  // rnAuthOpts is null from the gear, which never asks for it, so that door
  // leaves through the same test as a project with no remote.
  if (!rnAuthOpts || !rnAuthNow || $("rnTokenField").hidden){
    $("rnAuthField").hidden = true; return;
  }
  const typed = !!$("rnToken").value.trim();
  // What the project WILL have when Save lands, not what it has now: every
  // control here is staged, so they all have to agree about the same future.
  // A token survives unless it is being cleared; typing one is a new token
  // either way, which is also how you replace one you just cleared.
  const stored = rnAuthOpts.token && !rnClearToken;
  const canToken = stored || typed;
  const canKey = rnAuthOpts.ssh;

  const closed = stored && !rnClearToken;
  $("rnToken").disabled = closed;
  $("rnToken").placeholder = closed ? "stored: cleared below to replace it"
                                    : "ghp_… or github_pat_…";
  $("rnTokenClear").hidden = !(rnAuthOpts.token && !typed);
  $("rnTokenClear").textContent = rnClearToken
    ? "Keep the stored token after all"
    : "Clear the stored token, and type another";

  $("rnAuthField").hidden = false;
  // Disabled is always takeable: it is the absence of a credential rather than
  // the presence of one, and it is the honest answer for a project you want
  // pushing nowhere for now.
  $("rnAuthNone").disabled = false;
  $("rnAuthKey").disabled = !canKey;
  $("rnAuthToken").disabled = !canToken;
  segPick(["rnAuthNone", "rnAuthKey", "rnAuthToken"], {none: "rnAuthNone", ssh: "rnAuthKey", https: "rnAuthToken"}[rnAuthPick]);
  // The pick is NOT moved out from under the operator when clearing a token
  // takes its ground away. It stays where they put it and Save refuses, which
  // is the difference between being told and being corrected: silently sliding
  // to another mode is how you end up on a credential you did not choose.
  const invalid = rnAuthPick === "https" && !canToken;
  const changed = rnAuthPick !== rnAuthNow;
  $("rnAuthHint").classList.toggle("bad", invalid);
  $("rnAuthHint").textContent = invalid
    ? "Access token is picked but none will be stored: type one above, keep the "
      + "stored one, or pick Deploy key or Disabled."
    : (rnAuthNow === "ssh"
        ? "Pushes use the deploy key. "
      : rnAuthNow === "https"
        ? "Pushes use this project's access token. "
        : "Nothing is set, so a push is refused. ")
      + (changed
          ? (rnAuthPick === "https"
              ? "Saving switches pushes to the token; the key stays."
            : rnAuthPick === "ssh"
              ? "Saving switches pushes back to the deploy key; the token "
                + (rnClearToken ? "is cleared." : "stays stored.")
              : "Saving removes the credential; pushing is refused until you pick one.")
        : !canToken && !canKey
          ? "Nothing is stored to switch to: set a token above, or clone it "
            + "again with a deploy key."
        : !canToken
          ? "No token is stored for it: set one above and this becomes a choice."
        : !canKey
          ? "It has no deploy-key remote to go back to: it has only ever used https."
        : "Switching keeps every credential it has; nothing is removed either way.");
}

// Test (the operator, 7 Oct): a read and a dry-run push with what the
// project authenticates with, or with the token typed above and not saved
// yet, and what it is missing in red under the button (projects.auth_test).
async function rnTestAuth(){
  const btn = $("rnTest"), out = $("rnTestOut"), name = rnFor;
  if (!name || btn.disabled) return;
  busy(btn, "Testing");
  out.hidden = true;
  let j;
  try{
    j = await (await postJSON("/api/project-auth", {name, action: "test",
      token: $("rnToken").disabled ? "" : $("rnToken").value.trim()})).json();
  }catch{ j = {error: "no answer from the dashboard"}; }
  btn.disabled = false;
  btn.removeAttribute("aria-busy");
  btn.textContent = "Test";
  if (rnFor !== name) return;                   // closed, or reopened elsewhere
  const missing = j.missing || [];
  const good = !j.error && !missing.length;
  out.classList.toggle("bad", !good);
  out.classList.toggle("ok", good && j.push !== null);
  out.innerHTML = j.error ? esc(j.error)
    : missing.length
      ? `With ${esc(j.using)} it is missing:<ul>${missing.map(m => `<li>${esc(m)}</li>`).join("")}</ul>`
      : `With ${esc(j.using)} it can read${j.push ? " and push" : ""}.`;
  if (!j.error && (j.notes || []).length)
    out.innerHTML += `<div class="sub">${j.notes.map(esc).join(" ")}</div>`;
  out.hidden = false;
}

const rnAuthSet = m => { if (rnAuthPick === m) return; rnAuthPick = m; rnDrawAuth(); };

// A rename is the name shown and nothing else (R154): the directory, the
// notebook, the sessions and the containers stay where they are, so nothing
// has to be closed first.
// Where the project is on disk, and its id, under the name (the operator,
// 8 Oct): the name shown is a label, the folder is the project's for good.
function rnFolderLine(name){
  const pid = (state?.projects || []).find(p => p.name === name)?.pid;
  return `Folder: /workspace/${name}${pid ? ` · project #${pid}` : ""}. Renaming changes the name shown, never the folder.`;
}

// A shown name by GitHub's rules for a repository's, as the server keeps it
// (registry.clean_name): letters, digits, - _ and . only, each run of
// anything else one -, at most 100 (the operator, 9 Oct).
function ghName(raw){
  const s = String(raw || "").trim().replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "")
    .slice(0, 100).replace(/-+$/, "");
  return s === "." || s === ".." ? "" : s;
}

function rnShow(){
  const typed = $("rnName").value.trim(), raw = ghName(typed);
  $("rnHint").textContent = rnFolderLine(rnFor);
  const taken = raw && raw.toLowerCase() !== projLabel(rnFor).toLowerCase()
                && (state?.projects || []).some(p => p.name !== rnFor
                     && String(p.label || p.name).toLowerCase() === raw.toLowerCase());
  $("rnName").classList.toggle("bad", !!taken || !raw);
  $("rnPreview").classList.toggle("bad", !!taken || !raw);
  // Said as it is typed: the name it will be, when GitHub's rule changes it.
  const as = raw && raw !== typed;
  $("rnPreview").hidden = !taken && !!raw && !as;
  $("rnPreview").textContent = !raw ? "A project needs a name: letters, digits, - _ or ."
    : taken ? `${raw} is already a project's name`
    : `Saved as ${raw}: names follow GitHub's rule, letters, digits, - _ and . only`;
}

function closeRename(){
  // In place, closing is reading again: the saved values, once the poll has
  // them (or Revert's, the ones it had).
  if (rnHost){
    const n = rnFor, h = rnHost;
    settingsOut();
    rnFor = null;
    Promise.resolve(refresh()).finally(() => {
      if (h.isConnected && (state?.projects || []).some(p => p.name === n)) settingsInto(n, h);
    });
    return;
  }
  $("rnmodal").hidden = true; rnFor = null;
}

// ---- each section's own Save and Revert (the operator, 10 Oct) ---------------
// Every section that holds a setting carries its own Save and Revert at its
// foot, as the notebook's other views do (nb-core.js sectBar), and they write
// or put back that section's fields and nothing else. One Save at the foot of
// eleven sections was a long way from the field it saved, and its first press
// with a session running only asked a question: a person who pressed it once
// and moved on had saved nothing (Reads on BuilderBot, 10 Oct). Where the
// section holds something a running session takes only when it starts, its
// bar offers both answers at once: Save, keep it running and Save and end it.
const RN_SECTS = ["project", "people", "repo", "runs", "files", "sees", "tools", "build", "claude", "yours"];
// Which section each of rnPrefWas's fields is in, and what it is called.
const RN_WAS = {
  node: ["runs", "Node"], nodes: ["runs", "Node"], hosts: ["runs", "Hosts its containers on"], gpu: ["runs", "The node's GPU"], tests_in: ["runs", "Where tests run"],
  reads: ["sees", "Reads"], sees: ["sees", "Also sees"], reaches: ["sees", "Also reaches"],
  tc_off: ["tools", "Toolchains"], packs_on: ["tools", "Tool packs"],
  build: ["build", "Build"], test: ["build", "Test"], outputs: ["build", "Outputs"],
  capture_days: ["build", "Captures kept"], snapshot_days: ["build", "Snapshots kept"], snapshots_on: ["build", "Daily snapshots"], dev_keep: ["build", "Dev builds kept"],
  gate: ["claude", "Agents may"], test_change: ["claude", "During a test run, a change asked for"], agents_off: ["claude", "Coding agents"], agent_default: ["claude", "Start opens"], agent_slots: ["claude", "Sessions of one agent"],
  devbuild: ["claude", "Agents may"], makevms: ["claude", "Agents may"], vm_caps: ["claude", "Its VMs may hold"], report: ["claude", "Agents may"], sign: ["claude", "Agents may"],
  keys: ["claude", "Agents may"], release: ["claude", "Agents may"], pc: ["claude", "Agents may"], version: ["claude", "Move the version"],
  reply: ["yours", "Replies"], asks: ["yours", "Questions"], term_scheme: ["yours", "Terminal colors"],
  git_name: ["yours", "Commit name and email"], git_email: ["yours", "Commit name and email"],
};
// What a running session takes only when it starts (the briefing, the launch
// flags, the view it runs in); everything else is read when it is used.
const RN_AT_START = new Set(["reply", "asks", "git_name", "git_email", "node", "nodes",
                             "reads", "sees", "test_change", "gpu", "capture_days", "snapshot_days", "snapshots_on", "dev_keep",
                             "tc_off", "packs_on"]);

// The fields as they stand, in rnPrefWas's own shape, so each compares with
// its saved value directly.
function rnEnc(){
  // The node pickers are drawn once the node list has arrived: until then
  // they say nothing, and reading them as a change woke the Where it runs
  // bar on every open under load (the gate, 10 Oct).
  const drawn = nodesList !== null;
  const node = drawn ? $("rnNode").value : rnPrefWas.node;
  return {git_name: $("rnGitName").value.trim(), git_email: $("rnGitEmail").value.trim(),
          node, nodes: !drawn ? rnPrefWas.nodes
            : (node ? [node, ...[...$("rnNodesMore").querySelectorAll("input:checked")].map(i => i.value).filter(id => !rnHostIds().has(id))] : []).join(","),
          // The ticked rows marked Hosting only are prefs.hosts, the rest
          // prefs.nodes: one list on screen, two settings underneath.
          hosts: !drawn ? rnPrefWas.hosts : [...$("rnNodesMore").querySelectorAll("input:checked")].map(i => i.value).filter(id => rnHostIds().has(id)).join(","),
          reads: [...$("rnReads").querySelectorAll("input:checked")].map(i => i.value).join(","),
          // The rows are drawn once the node's toolchains have arrived;
          // until then the saved values stand, so an open is no change.
          tc_off: rnToolsList === null ? rnPrefWas.tc_off
            : rnRowsList(rnPrefWas.tc_off, $("rnTools").querySelectorAll("input[data-shipped]"), i => !i.checked),
          packs_on: rnToolsList === null ? rnPrefWas.packs_on
            : rnRowsList(rnPrefWas.packs_on, $("rnTools").querySelectorAll("input[data-pack]"), i => i.checked),
          agents_off: [...$("rnAgents").querySelectorAll("input:not(:checked)")].map(i => i.value).join(","),
          agent_default: $("rnAgentDefault")?.value || "claude",
          agent_slots: $("rnAgentSlots")?.value || "3",
          sees: $("rnSees").value.split(",").map(x => x.trim()).filter(Boolean).join(", "),
          reaches: JSON.stringify(rnReachNow()),
          build: $("rnBuildCmd").value.trim(), test: $("rnTestCmd").value.trim(),
          outputs: $("rnOutputs").value.trim(),
          capture_days: $("rnCaptureDays").value.trim(), snapshot_days: $("rnSnapDays").value.trim(),
          snapshots_on: $("rnSnapOn").checked ? "1" : "0",
          dev_keep: $("rnDevKeep").value.trim(), gate: gateKey(rnGateNow()),
          tests_in: $("rnDevTest").value || "node", test_change: $("rnTestChange").value || "wait",
          gpu: $("rnGpu").value || "on", reply: $("rnReply").value || "", asks: $("rnAsks").value || "",
          term_scheme: $("rnTermScheme").value || "",
          devbuild: $("rnGateDocker").value || "deny", makevms: $("rnGateVms").value || "deny", vm_caps: rnVmCapsNow(), report: $("rnGateReport").value || "auto",
          sign: $("rnGateSign").value || "ask", release: $("rnGateRelease").value || "ask",
          keys: $("rnGateKeys").value || "ask", pc: $("rnGatePc").value || "deny", version: $("rnGateVersion").value || "locked"};
}

// What one section holds unsaved, as the names its fields go by, and which
// of them a running session takes only at its start.
function rnSectChanges(sect, enc = rnEnc()){
  const said = [], start = [];
  for (const [k, [s, label]] of Object.entries(RN_WAS)){
    if (s !== sect || String(enc[k] ?? "") === String(rnPrefWas[k] ?? "")) continue;
    if (!said.includes(label)) said.push(label);
    if (RN_AT_START.has(k) && !start.includes(label)) start.push(label);
  }
  if (sect === "project"){
    if ($("rnName").value.trim().replace(/\s+/g, " ") !== projLabel(rnFor) && !$("rnNameField").hidden) said.unshift("Name");
  }
  if (sect === "people"){
    if (rnPeople && ((rnPeopleDraft.owner && rnPeopleDraft.owner !== rnPeople.owner)
        || (rnPeopleDraft.invite_only !== undefined && rnPeopleDraft.invite_only !== rnPeople.invite_only))) said.push("People");
  }
  if (sect === "repo"){
    if ($("rnToken").value.trim() || rnClearToken) said.push("Token");
    if (rnAuthPick && rnAuthPick !== rnAuthNow) said.push("Authentication");
    const a = $("rnAddr").value.trim();
    if (!$("rnAddrField").hidden && rnAuthOpts?.url && a && a !== rnAuthOpts.url) said.push("Address");
  }
  if (sect === "files" && rnFtpChange()) said.push("File access");
  return {said, start};
}

const rnDirty = () => RN_SECTS.filter(s => rnSectChanges(s).said.length);

// The bars, put in once and then kept in step with what is typed: dead
// rather than gone while there is nothing to save, so nothing moves under a
// thumb (sectBar's rule).
function rnBars(){
  if (rnFor === null) return;
  const enc = rnEnc(), running = !!myLiveSession(rnFor);
  for (const sect of RN_SECTS){
    const body = document.querySelector(`details.rngroup[data-sect="rn:${sect}"] > .body`);
    if (!body) continue;
    let bar = body.querySelector(":scope > .rnbarf > .rnbar");
    if (!bar){
      body.insertAdjacentHTML("beforeend", `<div class="field rnbarf"><div class="actbar sectbar rnbar" data-rnbar="${sect}">
        <span class="state"></span><span class="sp"></span>
        <button type="button" data-rnsave="${sect}">Save</button>
        <button type="button" data-rnkeep="${sect}" hidden>Save, keep it running</button>
        <button type="button" class="caution" data-rnrevert="${sect}">Revert</button>
        <button type="button" class="danger" data-rnend="${sect}" hidden>Save and end it</button></div></div>`);
      bar = body.querySelector(":scope > .rnbarf > .rnbar");
    }
    // A remote it can only read has nothing here to save (rnGitNone), nor
    // has the Settings view, which says what the remote is and opens its
    // door (rnRepoSum, B813).
    bar.parentElement.hidden = sect === "repo" && (!$("rnGitNone").hidden || !$("rnRepoSum").hidden);
    if (bar.dataset.busy) continue;
    const {said, start} = rnSectChanges(sect, enc);
    const ask = running && start.length > 0;
    const st = bar.querySelector(".state");
    if (!st.classList.contains("bad"))
      st.textContent = !said.length ? ""
        : ask ? `${said.join(", ")} changed; its running session takes ${start.join(", ")} only when it starts`
        : `${said.join(", ")} changed`;
    bar.querySelector("[data-rnsave]").hidden = ask;
    bar.querySelector("[data-rnkeep]").hidden = bar.querySelector("[data-rnend]").hidden = !ask;
    for (const b of bar.querySelectorAll("button")) b.disabled = !said.length;
  }
}

// One section put back to what it was when the settings were drawn or last
// saved; the other sections keep what is typed in them.
function rnRevertSect(sect){
  const w = rnPrefWas;
  if (sect === "project"){
    $("rnName").value = projLabel(rnFor); rnShow();
    $("rnPreview").hidden = true; $("rnName").classList.remove("bad");
  } else if (sect === "people"){
    rnPeopleDraft = {}; rnDrawPeople();
  } else if (sect === "repo"){
    $("rnToken").value = ""; rnClearToken = false; rnAuthPick = rnAuthNow;
    if (rnAuthOpts?.url) $("rnAddr").value = rnAuthOpts.url;
    rnDrawAuth();
  } else if (sect === "runs"){
    delete $("rnNodesMore").dataset.drawn;
    rnFillNode();
    $("rnGpu").value = w.gpu; $("rnDevTest").value = w.tests_in;
  } else if (sect === "files"){
    rnFtpDraft = {}; rnDrawFtp();
  } else if (sect === "tools"){
    rnFillTools();
  } else if (sect === "sees"){
    rnFillReads();
    $("rnSees").value = w.sees;
    $("rnReachRows").innerHTML = "";
    rnReachDraft = JSON.parse(w.reaches || "[]");
    rnDrawReach();
  } else if (sect === "build"){
    $("rnBuildCmd").value = w.build; $("rnTestCmd").value = w.test; $("rnOutputs").value = w.outputs;
    $("rnCaptureDays").value = w.capture_days; $("rnSnapDays").value = w.snapshot_days;
    $("rnSnapOn").checked = w.snapshots_on !== "0";
    $("rnDevKeep").value = w.dev_keep;
  } else if (sect === "claude"){
    const g = String(w.gate).split(",");
    Object.values(GATE_IDS).forEach((id, i) => { $(id).value = g[i] || "auto"; });
    $("rnTestChange").value = w.test_change; $("rnGateDocker").value = w.devbuild; $("rnGateVms").value = w.makevms; rnVmCapsSet(w.vm_caps);
    rnFillAgents(w.agents_off, w.agent_default);
    $("rnAgentSlots").value = w.agent_slots;
    $("rnGateReport").value = w.report; $("rnGateSign").value = w.sign;
    $("rnGateRelease").value = w.release; $("rnGateKeys").value = w.keys;
    $("rnGatePc").value = w.pc; $("rnGateVersion").value = w.version;
  } else if (sect === "yours"){
    $("rnReply").value = w.reply; $("rnAsks").value = w.asks; $("rnTermScheme").value = w.term_scheme;
    $("rnGitName").value = w.git_name; $("rnGitEmail").value = w.git_email;
    rnDrawPrefs();
  }
  rnBarSay(sect, "");
  rnBars();
}

// A sentence on one section's bar: an error in red, or nothing.
function rnBarSay(sect, msg, bad = true){
  const st = document.querySelector(`.rnbar[data-rnbar="${sect}"] .state`);
  if (!st) return;
  st.textContent = msg;
  st.classList.toggle("bad", !!msg && bad);
}

// rnPrefWas's shape back into what the server is sent.
function rnDec(w){
  const g = String(w.gate || "").split(",");
  return {...w,
    nodes: String(w.nodes || "").split(",").filter(Boolean),
    hosts: String(w.hosts || "").split(",").filter(Boolean),
    reads: String(w.reads || "").split(",").filter(Boolean),
    sees: String(w.sees || "").split(",").map(x => x.trim()).filter(Boolean),
    reaches: JSON.parse(w.reaches || "[]"),
    gate: Object.fromEntries(Object.keys(GATE_IDS).map((k, i) => [k, g[i] || "auto"]))};
}

// One section's Save: its own fields sent, every other section's as they
// were saved, so nothing typed elsewhere goes with it. `end` is the answer
// to a running session, from the bar's two buttons.
async function rnSubmit(sect, end = false){
  const name = rnFor;
  const bar = document.querySelector(`.rnbar[data-rnbar="${sect}"]`);
  const fail = m => { rnBarSay(sect, m); return false; };
  rnBarSay(sect, "");
  const enc = rnEnc();
  const mine = Object.keys(RN_WAS).filter(k => RN_WAS[k][0] === sect);
  // What this section holds that somebody else saved since these settings
  // were opened (another person, another window): refused once, naming it,
  // so their change is not written over unseen (the operator, 17 Oct); a
  // second press writes this one's over it. Read against the project as it
  // is now, the poll asked first.
  if (typeof refresh === "function") await refresh().catch(() => {});
  const now = rnPrefsOf((state?.projects || []).find(x => x.name === name));
  const theirs = mine.filter(k => k !== "version" && String(now[k] ?? "") !== String(rnPrefWas[k] ?? "")
                               && String(now[k] ?? "") !== String(enc[k] ?? ""));
  const said = [...new Set(theirs.map(k => RN_WAS[k][1]))];
  if (said.length && bar?.dataset.over !== said.join()){
    if (bar) bar.dataset.over = said.join();
    return fail(`${said.join(", ")} changed since these settings were opened, by someone else or another window: `
                + "Revert shows what is saved now, or Save again to write yours over it");
  }
  if (bar) delete bar.dataset.over;
  const merged = {...rnPrefWas, ...Object.fromEntries(mine.map(k => [k, enc[k]]))};
  const v = rnDec(merged);
  const {start} = rnSectChanges(sect, enc);
  const prefsChanged = mine.some(k => k !== "version" && String(enc[k] ?? "") !== String(rnPrefWas[k] ?? ""));
  const running = !!myLiveSession(name);
  // The name and the remote are their own sections' alone.
  const to = sect === "project" ? $("rnName").value : projLabel(name);
  const token = sect === "repo" ? $("rnToken").value.trim() : "";
  const auth = sect === "repo" && rnAuthPick && rnAuthPick !== rnAuthNow ? rnAuthPick : "";
  const clear_token = sect === "repo" && rnClearToken && !token;
  const addrNow = $("rnAddr").value.trim();
  const address = sect === "repo" && !$("rnAddrField").hidden && rnAuthOpts?.url && addrNow && addrNow !== rnAuthOpts.url
    ? addrNow : "";
  if (!to.trim()) return fail("a new name is needed");
  if (merged.capture_days !== "" && !/^\d{1,3}$/.test(merged.capture_days))
    return fail("captures kept is a number of days, 0 to 365");
  if (merged.snapshot_days !== "" && !/^\d{1,4}$/.test(merged.snapshot_days))
    return fail("snapshots kept is a number of days, 0 to 3650");
  if (merged.dev_keep !== "" && !/^\d{1,2}$/.test(merged.dev_keep))
    return fail("dev builds kept is a number of builds, 0 to 99");
  // The one combination this will not write: authenticating with a token it
  // is being told to throw away.
  if (sect === "repo" && rnAuthPick === "https" && !((rnAuthOpts?.token && !rnClearToken) || token))
    return fail("pick a credential that will exist: there will be no access token after this save");
  const renaming = to.trim().replace(/\s+/g, " ") !== projLabel(name);
  const needRename = renaming || !!token || !!auth || clear_token || !!address;
  const restartNow = !!end && running && start.length > 0;
  bar.dataset.busy = "1";
  const pressed = bar.querySelector(end ? "[data-rnend]" : running && start.length ? "[data-rnkeep]" : "[data-rnsave]");
  const word = pressed.textContent;
  bar.querySelectorAll("button").forEach(b => { b.disabled = true; });
  busy(pressed, "Saving");
  const stop = m => { delete bar.dataset.busy; unbusy(pressed, word); rnBars(); return fail(m); };
  try{
    if (prefsChanged){
      // This section's own fields alone (the operator, 17 Oct): every field
      // went with every save, the others as this window last read them, so a
      // save here put back what somebody had changed in another section.
      const only = new Set(mine);
      const pick = o => Object.fromEntries(Object.entries(o).filter(([k]) => only.has(k)));
      const r = await fetch("/api/prefs", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({project: name, restart: restartNow, ...pick({git_name: v.git_name, git_email: v.git_email,
                              node: v.node, nodes: v.nodes, hosts: v.hosts, reads: v.reads, sees: v.sees, reaches: v.reaches,
                              tc_off: v.tc_off, packs_on: v.packs_on, agents_off: v.agents_off, agent_default: v.agent_default, agent_slots: v.agent_slots,
                              build: v.build, test: v.test, gate: v.gate,
                              tests_in: v.tests_in, test_change: v.test_change, gpu: v.gpu, reply: v.reply, asks: v.asks, term_scheme: v.term_scheme,
                              devbuild: v.devbuild, makevms: v.makevms, vm_caps: JSON.parse(v.vm_caps || "{}"), report: v.report, sign: v.sign, keys: v.keys, release: v.release, pc: v.pc,
                              outputs: v.outputs.split(",").map(x => x.trim()).filter(Boolean),
                              ...(v.capture_days !== "" ? {capture_days: +v.capture_days} : {}),
                              ...(v.snapshot_days !== "" ? {snapshot_days: +v.snapshot_days} : {}),
                              snapshots_on: v.snapshots_on !== "0",
                              ...(v.dev_keep !== "" ? {dev_keep: +v.dev_keep} : {})})})});
      const j = await r.json();
      if (j.error) return stop(j.error);
      // Said out loud when the session was left on what it started with,
      // and why, and when it was ended.
      if (running && start.length && !j.ended)
        notify(restartNow
                 ? `${projLabel(name)}: saved, but the session was not ended: ` + (j.why || "it is still on what it started with")
                 : `${projLabel(name)}: saved. Its running session keeps what it started with until you end it and press Start agent again.`,
               restartNow);
      else if (restartNow && j.ended)
        notify(`${projLabel(name)}: saved, and its session ended: press Start agent to start one on it, resuming the conversation`);
    }
    if (sect === "people" && rnPeople && ((rnPeopleDraft.owner && rnPeopleDraft.owner !== rnPeople.owner)
        || (rnPeopleDraft.invite_only !== undefined && rnPeopleDraft.invite_only !== rnPeople.invite_only))){
      const why = await rnSavePeople(name);
      if (why) return stop(why);
      rnLoadPeople(name);
    }
    // Move the version is version.py's policy: written where the Artifacts
    // tab writes it, so the two never disagree.
    if (sect === "claude" && enc.version !== rnPrefWas.version){
      const j = await (await postJSON("/api/version", {project: name, action: "policy", policy: enc.version})).json();
      if (j.error) return stop(j.error);
    }
    const ftpChange = sect === "files" ? rnFtpChange() : null;
    if (ftpChange){
      const why = await rnSaveFtp(name, ftpChange);
      if (why) return stop(why);
      rnLoadFtp(name);
    }
    if (needRename){
      const r = await postJSON("/api/rename", {name, to, token, auth, clear_token, address});
      const j = await r.json();
      if (j.error) return stop(j.error);
      notify(renaming ? `${j.from || projLabel(name)} is now ${j.label || to}`
        : address ? `${projLabel(name)}: ${(j.moved || []).find(m => /points at/.test(m)) || "saved"}`
        : `${projLabel(name)} saved`);
      // A new name is a new project key everywhere: drawn again under it.
      if (renaming){ delete bar.dataset.busy; closeRename(); refresh(); return true; }
      $("rnToken").value = ""; rnClearToken = false;
      rnLoadAuth(name);
    }
  }catch(e){ return stop("save failed: " + e); }
  // Saved: what this section shows is now what is saved, and the rest keep
  // what is typed in them.
  rnPrefWas = merged;
  delete bar.dataset.busy;
  unbusy(pressed, word);
  rnBarSay(sect, "");
  rnBars();
  refresh();
  return true;
}


// Deleting asks once and says where the files go, rather than asking twice or
// making somebody type the name. The roadmap item this came from called for a
// typed confirmation, on the reasoning that it would be the one control here
// destroying work outside /config, and it is not that any more: the directory
// is moved to /workspace/.trash with everything in it, and the notebook is not
// touched at all. Putting one back is a mv. Friction proportionate to a
// reversible act, and the dialog names the path so the reversal is obvious.
async function deleteProject(name){
  // What keeps running with no project while it is in the trash (the
  // operator, 26 Oct), said before it is asked.
  const own = await postJSON("/api/repos", {action: "owned", name}).then(r => r.json()).catch(() => ({}));
  const left = [own.containers?.length ? `Its container${own.containers.length === 1 ? "" : "s"} ${own.containers.join(", ")} keep${own.containers.length === 1 ? "s" : ""} running, given to no project until it is put back.` : "",
                own.vms?.length ? `Its VM${own.vms.length === 1 ? "" : "s"} ${own.vms.join(", ")} keep${own.vms.length === 1 ? "s" : ""} running under No project, an administrator's to act on.` : ""].filter(Boolean).join(" ");
  if (!await askYes(`Delete ${projLabel(name)}?\n\n`
      + `It moves to /workspace/.trash/${name}, with every file kept. Its `
      + `roadmap, bugs, versions and memories stay where they are, `
      + `and Put back in the trash returns all of it.${left ? "\n\n" + left : ""}\n\n`
      + `Close its terminals first.`)) return;
  try{
    const r = await postJSON("/api/trash", {name});
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    // The path is named back because it may not be the one the dialog said:
    // a second delete of the same name is numbered rather than overwriting the
    // first, and the first is exactly the copy somebody would want back.
    notify(`${projLabel(name)} moved to ${j.to}`);
  }catch(e){ notify("delete failed: " + failWords(e), true); }
  refresh();
}
