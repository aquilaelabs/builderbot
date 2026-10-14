// A project's settings dialog: its name, its nodes, the model and effort
// every session starts on, its color, the dials of what Claude may do
// there, the git credential, and the submit that applies each change in
// turn. Unlinking and deleting a project start here too.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
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
                 node: "", nodes: "", hosts: "", reads: "", sees: "", reaches: "", build: "", test: "", outputs: "",
                 capture_days: "7", snapshot_days: "14", dev_keep: "3", gate: "", color: "", debug: ""};
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
const projectColor = name =>
  (state?.projects || []).find(x => x.name === name)?.prefs?.color || "";
// The name a project is shown under (R154): its directory is `name` and the
// key everywhere, and what a person reads is the registry's `label`. A name
// not in the poll (a project since deleted) is shown as it is.
const projLabel = name =>
  (state?.projects || []).find(x => x.name === name)?.label || String(name ?? "");
// The project a tab is about, for its color: a notebook's, or the project
// whose Claude session a terminal tab holds. A plain shell has none.
const tabProject = t => t.kind === "notebook" ? t.arg
  : t.kind === "term" && String(t.arg).startsWith("claude:") ? t.arg.slice(7).split(":")[0] : "";
const rnColorNow = () =>
  $("rnColor").querySelector('[aria-checked="true"]')?.dataset.color || "";
function rnFillColor(cur){
  $("rnColor").innerHTML = PROJECT_COLORS.map(([n, tone]) =>
    `<button type="button" role="radio" data-color="${n}" aria-checked="${n === cur}"
       aria-label="${esc(n || "none")}" title="${esc(n || "none")}"${
       n ? ` style="--pc:${tone}"` : ""}></button>`).join("");
}
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

function rnFillPrefs(p){
  // A fresh open draws the node list from what is saved, not from the ticks
  // the last project's dialog left in it (the merged list, 13 Oct).
  const nm = $("rnNodesMore");
  if (nm) delete nm.dataset.drawn;
  rnPrefWas = {git_name: p?.yours?.git_name || "", git_email: p?.yours?.git_email || "",
               node: p?.prefs?.node || "",
               nodes: (p?.prefs?.nodes || []).join(","),
               hosts: (p?.prefs?.hosts || []).join(","),
               reads: (p?.prefs?.reads || []).join(","),
               sees: (p?.prefs?.sees || []).join(", "),
               reaches: JSON.stringify(p?.prefs?.reaches || []),
               debug: rnDebugKey(p?.prefs?.diag, p?.prefs?.log_from),
               build: p?.prefs?.build || "", test: p?.prefs?.test || "",
               outputs: (p?.prefs?.outputs || []).join(", "),
               capture_days: String(p?.prefs?.capture_days ?? 7),
               snapshot_days: String(p?.prefs?.snapshot_days ?? 14),
               dev_keep: String(p?.prefs?.dev_keep ?? 3),
               gate: gateKey(p?.prefs?.gate),
               tests_in: p?.prefs?.tests_in || "node",
               test_change: p?.prefs?.test_change || "wait",
               gpu: p?.prefs?.gpu || "on",
               reply: p?.yours?.reply || "", asks: p?.yours?.asks || "",
               devbuild: devClaudeMode(rnFor),
               report: p?.prefs?.report || "auto",
               sign: p?.prefs?.sign || "ask",
               release: p?.prefs?.release || "ask",
               keys: p?.prefs?.keys || "ask",
               version: p?.version_policy || "locked",
               color: p?.prefs?.color || ""};
  rnFillColor(rnPrefWas.color);
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
  rnFillDebug();
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
      loadNodes().then(() => { if (opened !== null && rnFor === opened){ rnFillNode(); rnFillDebug(); rnBars(); } });
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
    sel.innerHTML = `<option value="">none: no builds, tests or Claude sessions until one is picked</option>`
      + gone
      + pick.map(n => `<option value="${esc(n.id)}"${n.id === rnPrefWas.node ? " selected" : ""}>${
          esc(n.name)} (${esc(n.kind)}, ${esc(n.state)}${n.live === false ? ", quiet" : ""}${
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
  const ns = rnReachNodes(), ro = !state?.admin;
  box.innerHTML = rnReachDraft.map((e, i) => `<div class="rnreach" data-i="${i}">
      <input data-reach value="${esc(e.addr)}" autocomplete="off" spellcheck="false" placeholder="192.168.1.20 or 192.168.1.20:8080"
        aria-label="an address a session here may reach"${ro ? " disabled" : ""}>
      ${ns.length > 1 ? `<span class="rnreachnodes">${ns.map(n => `<label class="ndcap"><input type="checkbox" data-reachnode value="${esc(n.id)}"${
        !e.nodes.length || e.nodes.includes(n.id) ? " checked" : ""}${ro ? " disabled" : ""}> ${esc(n.name)}</label>`).join("")}</span>` : ""}
      ${ro ? "" : `<button type="button" class="eye rm" data-reachrm aria-label="remove this address" title="remove this address">${BIN}</button>`}
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
  // Whether it does anything yet: only where a node filters (its row's switch).
  const off = ns.filter(n => !n.config?.session_net).map(n => n.name);
  $("rnReachHint").textContent = !ns.length ? ""
    : off.length === ns.length ? `${off.join(", ")} lets sessions reach the whole network now, so this applies once it keeps each session to its own project's.`
    : off.length ? `Applies on the nodes that keep sessions to their own network; ${off.join(", ")} does not yet.`
    : "An address for the whole machine, or address:port for one service.";
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
  box.dataset.drawn = "1";
  // Also reaches ticks among these, so it is drawn after them.
  rnDrawReach();
}

// The projects a session here may read: every other project this account
// sees, a listbox row each, ticked from the settings. Read-only there by
// construction (users.with_reads), so the hint under it can say so plainly.
// What a session here may read for debugging (the operator, 6 Oct): the
// controller's diagnostics, then each node's machine logs, a listbox row
// each. The debug grant's, and not drawn at all for an account without it.
const rnDebugKey = (diag, from) => (diag ? "diag;" : "") + [...(from || [])].sort().join(",");
function rnFillDebug(){
  const box = $("rnDebug"), wrap = $("rnDebugField");
  if (!box) return;
  const p = (state?.projects || []).find(x => x.name === rnFor);
  const was = new Set(p?.prefs?.log_from || []);
  const rows = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  // ...and only where debug mode is on, which needs a controller started
  // with DEBUG_MODE=1 (settings.debug_available).
  wrap.hidden = rnMode === "git" || state?.can?.debug === false || !state?.settings?.settings?.debug_mode?.value;
  box.innerHTML = lrow("@diag", "The controller's diagnostics", "bb diag", !!p?.prefs?.diag)
    + rows.map(n => lrow(n.id, n.name, "machine logs", was.has(n.id))).join("");
}
function rnDebugNow(){
  const on = [...$("rnDebug").querySelectorAll("input:checked")].map(i => i.value);
  return {diag: on.includes("@diag"), log_from: on.filter(v => v !== "@diag")};
}

function rnFillReads(){
  const box = $("rnReads"), wrap = $("rnReadsField");
  if (!box) return;
  const was = new Set(rnPrefWas.reads.split(",").filter(Boolean));
  const others = (state?.projects || []).filter(p => p.name !== rnFor)
    .sort((a, b) => a.name.localeCompare(b.name));
  wrap.hidden = rnMode === "git" || !others.length;
  box.innerHTML = others.map(p => lrow(p.name, projLabel(p.name), p.branch ? `git: ${p.branch}` : "", was.has(p.name))).join("");
  // BuilderBot's owner's alone (the operator, 6 Oct): shown to everybody,
  // changed by the owner, and why not said on the row (not a tooltip).
  const mine = state?.can?.reads !== false;
  box.querySelectorAll("input").forEach(i => { i.disabled = !mine; });
  $("rnReadsWhy").hidden = mine;
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
  $("rnOutputs").value = (p?.prefs?.outputs || []).join(", ");
  $("rnCaptureDays").value = String(p?.prefs?.capture_days ?? 7);
  $("rnSnapDays").value = String(p?.prefs?.snapshot_days ?? 14);
  $("rnDevKeep").value = String(p?.prefs?.dev_keep ?? 3);
  for (const [k, id] of Object.entries(GATE_IDS)){
    const el = $(id);
    if (el.dataset.built !== "1"){
      el.innerHTML = gateChoices(k).map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = p?.prefs?.gate?.[k] || "auto";
  }
  {
    // Auto and deny only: a report has nothing to hold for approval.
    const el = $("rnGateReport");
    if (el.dataset.built !== "1"){
      el.innerHTML = GATE_MODES.filter(([v]) => v !== "ask")
        .map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = p?.prefs?.report || "auto";
  }
  {
    const el = $("rnGateSign");
    if (el.dataset.built !== "1"){
      el.innerHTML = GATE_MODES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = p?.prefs?.sign || "ask";
  }
  {
    const el = $("rnGateRelease");
    if (el.dataset.built !== "1"){
      el.innerHTML = GATE_MODES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = p?.prefs?.release || "ask";
  }
  {
    const el = $("rnGateKeys");
    if (el.dataset.built !== "1"){
      el.innerHTML = GATE_MODES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = p?.prefs?.keys || "ask";
  }
  {
    const el = $("rnGateVersion");
    if (el.dataset.built !== "1"){
      el.innerHTML = Object.entries(POLICY_LABEL).map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = p?.version_policy || "locked";
  }
  {
    const el = $("rnGateDocker");
    if (el.dataset.built !== "1"){
      el.innerHTML = GATE_MODES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = devClaudeMode(rnFor);
    // docker-write's to change (the grant, R137 step 4), so not offered otherwise.
    el.closest("label").hidden = state?.can?.["docker-write"] === false;
  }
  rnDrawPrefs();
}

function rnDrawPrefs(){
  const p = (state?.projects || []).find(x => x.name === rnFor);
  // Ghosted where no session can start: a locked project is the operator's
  // to run. The model and effort are not here any more: a session starts on
  // the ones picked in the Claude button's menu each time (the operator, 12
  // Oct).
  const shut = !!p?.locked;
  $("rnReply").disabled = $("rnAsks").disabled = shut;
  $("rnPrefHint").textContent = shut
    ? "Locked; this project is yours to run, so no session starts here."
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
  if (!confirm(`Unlink ${projLabel(name)} from ${where}?\n\n`
      + `The remote and its stored token go; every commit and branch stays. `
      + `You can link it elsewhere afterwards.`)) return;
  const stop = m => { $("rnErr").textContent = m; $("rnErrWrap").hidden = false;
                      $("rnUnlink").disabled = false;
                      $("rnUnlink").textContent = `Unlink from ${p?.forge_name || "its remote"}`; };
  $("rnUnlink").disabled = true; $("rnUnlink").textContent = "Unlinking…";
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

// The form shown in a notebook's Settings view instead of the dialog (R119
// step 3): one form, moved to where it is wanted. `rnHost` is the view's
// .modal.inline while the form is there, else null and the form is the
// dialog's.
let rnHost = null;
function settingsOut(){
  if (!rnHost) return;
  const box = rnHost.querySelector(":scope > .box");
  if (box) $("rnmodal").appendChild(box);
  rnHost = null;
  $("rnCancel").hidden = false;
}
function settingsInto(name, host){
  if (!host) return;
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
}
// A project's settings: its notebook's Settings view.
function openProjectSettings(name){ openNotebook(name, "settings"); }

function renameProject(name, mode = "all"){
  settingsOut();
  rnFor = name;
  rnMode = mode;
  const p = (state?.projects || []).find(x => x.name === name);
  // One dialog, two doors. The gear is the project's own settings; the chain
  // is the remote's half of them, and opening it there hides everything that
  // is not about the remote rather than scrolling past it.
  const git = mode === "git";
  // Named rather than assumed: a project on somebody's own Gitea should not
  // read "GitHub settings", and the host is the one fact this door is about.
  const where = p?.forge_name || "its remote";
  $("rnTitle").textContent = git ? `${where} settings for ${projLabel(name)}` : projLabel(name);
  for (const id of ["rnNameField", "rnColorField", "rnMineField",
                    "rnGateField", "rnBuildField", "rnReadsField"])
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
      : "Kept for this project alone; a shell here can read it.";
  // Nothing to set is an answer, not an empty box: a linked project with no
  // token and no push rights has a remote it can only read.
  $("rnGitNone").hidden = !(git && $("rnTokenField").hidden);
  if (!$("rnGitNone").hidden)
    $("rnGitNone").firstElementChild.textContent =
      `${projLabel(name)} has a remote it can only read, so there is no credential to set here.`;
  // Unlink is the chain's, never the gear's: it is about the remote, and it
  // is the way a project moves from one host to another, since linking
  // refuses a repo that already has one.
  $("rnUnlink").hidden = !(git && p?.linked);
  $("rnUnlink").textContent = `Unlink from ${p?.forge_name || "its remote"}`;
  // The bin, on the gear's door only: the chain's is about the remote.
  $("rnDelete").hidden = git || !p;
  $("rnKeyOut").hidden = true; $("rnKeyPaste").hidden = true; $("rnKeyPaste").value = "";
  rnLoadAuth(name);
  rnLoadSigning(name);
  rnLoadSnapshots(name);
  rnLoadPeople(name);
  rnLoadFtp(name);
  rnFillPrefs(p);
  // The sessions at the foot: the gear's door, and an administrator's.
  $("rnSessField").hidden = true;
  if (!git && state?.admin) rnSessionsLoad(name);
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

function rnLoadPeople(name){
  rnPeople = null; rnPeopleDraft = {};
  $("rnPeopleField").hidden = true;
  if (rnMode === "git") return;
  postJSON("/api/members", {action: "view", project: name})
    .then(r => r.json())
    .then(j => { if (rnFor !== name || j.error) return; rnPeople = j; rnDrawPeople(); })
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
  $("rnPeople").innerHTML = `
    <div class="setrow">${v.may_manage
      ? `<label class="ndcap" for="rnOwner">Owner</label>
         <select id="rnOwner">${v.accounts.map(n => `<option value="${esc(n)}"${n === owner ? " selected" : ""}>${esc(n)}</option>`).join("")}</select>`
      : `<span>Owner: ${esc(v.owner || "BuilderBot's owner")}</span>`}</div>
    ${v.may_manage && !v.bb_owner && d.owner && d.owner !== v.owner
      ? `<div class="sub">Saving offers it to ${esc(d.owner)}, who becomes its owner on accepting from their bell.</div>` : ""}
    ${v.offer ? `<div class="rninvite">Ownership offered to ${esc(v.offer.name)} <span class="dim">${esc(ago(v.offer.at))}, waiting for them to accept</span>
      ${v.may_manage ? `<button type="button" class="link" data-withdraw="${v.offer.id}">Withdraw</button>` : ""}</div>` : ""}
    <label class="ndcap"><input type="checkbox" id="rnInviteOnly"${only ? " checked" : ""}${v.may_manage ? "" : " disabled"}>
      Invite only</label>
    <div class="sub whoson">On it: ${v.members.length ? v.members.map(esc).join(", ") : "nobody yet"}${
      v.may_manage ? ` · <button type="button" class="link" id="rnRolesGo">Roles on this project</button>` : ""}</div>
    ${v.invites.map(i => `<div class="rninvite">${esc(i.name)} <span class="dim">invited${i.role ? ` as ${esc(i.role)}` : ""} by ${esc(i.by || "somebody")} ${esc(ago(i.at))}</span>
      <button type="button" class="link" data-withdraw="${i.id}">Withdraw</button></div>`).join("")}
    ${v.may_invite && invitable.length ? (v.roles || []).length ? `<div class="rninvitebar">
      <select id="rnInviteWho" aria-label="account to invite">${invitable.map(n => `<option>${esc(n)}</option>`).join("")}</select>
      <select id="rnInviteRole" aria-label="the role they are invited as">${v.roles.map(n => `<option>${esc(n)}</option>`).join("")}</select>
      <button type="button" id="rnInviteGo">Invite</button></div>`
      : `<div class="sub warn">no role on this project to invite anybody with: add one on the Roles tab</div>` : ""}`;
  const o = $("rnOwner");
  if (o) o.onchange = () => { d.owner = o.value; rnDrawPeople(); };
  // What each person may do here is the Roles tab's (R152): a project's
  // owner gives its roles there, on the projects they own.
  const rg = $("rnRolesGo");
  if (rg) rg.onclick = () => openRolesTab();
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
  if (!v.may_set){
    $("rnFtpField").hidden = !v.on && !v.editor;
    box.innerHTML = `${v.on ? `<div>Served over FTPS${where ? `, at ${esc(where)}` : ""}.</div>` : ""}
      ${v.editor ? `<div>Open in an editor with BuilderBot for VS Code.</div>` : ""}
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
    <label class="ndcap"><input type="checkbox" id="rnFtpEditor"${editor ? " checked" : ""}> Open them in an editor with BuilderBot for VS Code</label>
    ${editor ? `<div class="hint">Through this controller, as each person's own account: no share and no port of its own.</div>` : ""}
    ${v.node || !on ? "" : `<div class="hint bad">It has no node to run on: pick one under Where it runs.</div>`}
    <div class="logdays setrow"${on ? "" : " hidden"}><label class="ndcap" for="rnFtpPort">Port<span class="help" data-help="the port and the ${v.span - 1} after it, which carry the data; projects on one node are kept ${v.span} ports apart" tabindex="0">?</span></label>
      <input id="rnFtpPort" type="number" min="1024" max="65526" step="1" inputmode="numeric" value="${esc(String(port))}" aria-label="the port its FTP server listens on">
      <span class="dim">and the ${v.span - 1} after it</span></div>
    ${status}
    <div class="rnftppeople"${on || editor ? "" : " hidden"}>${v.people.map(p => {
      const a = d.access?.[p.uid] ?? p.access;
      return `<div class="rnftprow"><span class="grow">${esc(p.name)}</span>
        <select data-ftpuid="${esc(p.uid)}" aria-label="${esc(p.name)}'s file access">${RN_FTP_ACCESS.map(([k, w]) =>
          `<option value="${k}"${k === a ? " selected" : ""}>${w}</option>`).join("")}</select></div>`;
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

// ---- signing keys (R106) ----
// A project's Android keys, an administrator's: named keys (default first),
// each with a Play upload slot and a sideload signing slot, and which of the
// project's apps (by package) signs with which key. The controller keeps
// them and bb sign uses them on the node; the dialog only ever sees aliases
// and fingerprints. An upload, a removal and a mapping are a draft until
// Save; Generate and Download backup are actions and act on the press.
const RN_SIGN = [
  ["play", "Play upload key",
   "For Google Play with Play App Signing, which can reset a lost upload key."],
  ["sideload", "Sideload signing key",
   "Signs a build handed out directly. Lose it and no update reaches an existing install: keep a copy offline."]];
let rnSignKeys = null, rnSignTool = false, rnSignDraft = {}, rnSignMap = {}, rnSignMapDraft = {}, rnSignNew = [],
    rnSignBackup = false, rnSignLocked = false, rnSignMayLock = false, rnSignLockOpen = false, rnSignPw = {};

function rnLoadSigning(name){
  rnSignKeys = null; rnSignDraft = {}; rnSignMapDraft = {}; rnSignNew = [];
  $("rnSignField").hidden = true;
  if (rnMode === "git" || !state?.admin) return;
  postJSON("/api/signing", {action: "list", project: name})
    .then(r => r.json())
    .then(j => {
      if (rnFor !== name || j.error) return;
      rnSignKeys = j.keys || {}; rnSignMap = j.map || {}; rnSignTool = !!j.keytool;
      rnSignBackup = !!j.may_backup;
      rnSignLocked = !!j.backup_locked; rnSignMayLock = !!j.may_lock;
      rnDrawSigning();
    })
    .catch(() => {});
}

const rnFp = sha => sha ? `${sha.slice(0, 8)}…${sha.slice(-8)}` : "";

// The project's daily snapshots (R165): each day kept, with Restore for the
// whole tree and a box to restore one file. An administrator's, and acted on
// at the press after a confirmation, not staged with Save: a restore is the
// thing done when something went wrong, and it first snapshots the tree as
// it is, so the line it leaves says how to undo it.
let rnSnap = null;

function rnLoadSnapshots(name){
  rnSnap = null;
  $("rnSnapField").hidden = true;
  if (rnMode === "git" || !state?.admin) return;
  fetch("/api/snapshots?project=" + encodeURIComponent(name))
    .then(r => r.json())
    .then(j => { if (rnFor === name && !j.error){ rnSnap = j; rnDrawSnapshots(); } })
    .catch(() => {});
}

function rnDrawSnapshots(){
  if (!rnSnap) return;
  const name = rnFor;
  $("rnSnapField").hidden = false;
  const days = rnSnap.days || [];
  const when = d => d.at ? new Date(d.at * 1000).toLocaleString([], {dateStyle: "medium", timeStyle: "short"}) : d.day;
  $("rnSnapRows").innerHTML = (days.length ? days.map(d => `<div class="rnsnap actbar" data-day="${esc(d.day)}">
      <span class="grow">${esc(when(d))}${d.why ? ` <span class="dim">(${esc(d.why.replace(/-/g, " "))})</span>` : ""}
        <span class="dim">· ${d.files} files · ${esc(humanBytes(d.bytes))}</span></span>
      <input type="text" data-snapfile placeholder="a file, from the tree's top" spellcheck="false" autocomplete="off"
             aria-label="the file to restore from this day">
      <button type="button" data-snapone>Restore file</button>
      <button type="button" data-snapall>Restore all</button>
    </div>`).join("")
    : `<div class="dim">none yet: the first is taken within half an hour of the setting being above 0</div>`)
    + `<div class="actbar"><button type="button" data-snaptake>Take one now</button></div>`;
  $("rnSnapHint").textContent = rnSnap.keep
    ? `One a day, kept ${rnSnap.keep} day${rnSnap.keep === 1 ? "" : "s"}. A restore snapshots the tree first, so it can be undone from the line it leaves.`
    : "Snapshots kept is 0, so none are taken; the ones here go at the next daily look.";
  const act = async (b, body, ask) => {
    if (ask && !confirm(ask)) return;
    await pressing(b, async () => {
      const r = await postJSON("/api/snapshots", {project: name, ...body});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      notify(body.action === "take" ? `snapshot taken: ${j.files} files`
        : `restored: ${j.wrote} written, ${j.removed} removed; undo from ${j.undo}`);
      rnLoadSnapshots(name);
    });
  };
  $("rnSnapRows").querySelectorAll(".rnsnap").forEach(row => {
    const day = row.dataset.day;
    row.querySelector("[data-snapall]").onclick = e => act(e.target, {action: "restore", day},
      `Put all of ${name} back as it was on ${day}?\n\nFiles changed since are written back and files added since are removed, on the controller and then every node. The tree as it is now is snapshotted first.`);
    row.querySelector("[data-snapone]").onclick = e => {
      const path = row.querySelector("[data-snapfile]").value.trim();
      if (!path) return notify("type the file to restore, from the tree's top", true);
      act(e.target, {action: "restore", day, path}, `Put ${path} back as it was on ${day}?`);
    };
  });
  const take = $("rnSnapRows").querySelector("[data-snaptake]");
  if (take) take.onclick = e => act(e.target, {action: "take"}, "");
}

function rnDrawSigning(){
  if (!rnSignKeys || rnMode === "git") return;     // the remote's door alone (B539)
  $("rnSignField").hidden = false;
  const name = rnFor;
  const names = [...new Set([...Object.keys(rnSignKeys), ...rnSignNew])];
  if (!names.includes("default")) names.unshift("default");
  const slot = (key, route, word, about) => {
    const k = (rnSignKeys[key] || {})[route], d = rnSignDraft[`${key}:${route}`] || {};
    const now = d.remove ? `${word}: removed when you Save`
      : d.file ? `${word}: ${esc(d.file.name)}, kept when you Save`
      : k ? `${word}: ${esc(k.alias)} <span class="dim">${esc(rnFp(k.sha256))}${k.generated ? ", made here" : ""}</span>`
      : `${word}: none`;
    const never = k && !d.remove && !d.file && route === "sideload" && !k.backed_up;
    // Rotation (R106 step 7): what this key was rotated to or from, and the
    // keys it could hand an app to.
    const retired = route === "sideload" && k?.retired_for, rotated = route === "sideload" && k?.rotated_from;
    const targets = route === "sideload" && k && !retired ? Object.entries(rnSignKeys)
      .filter(([n, s]) => n !== key && s.sideload && !s.sideload.retired_for && !s.sideload.rotated_from).map(([n]) => n) : [];
    return `<div class="rnsign" data-key="${esc(key)}" data-route="${route}">
      <div>${now}</div>
      <div class="sub dim">${esc(about)}${k && !d.remove && !d.file
        ? ` ${k.backed_up ? `Backed up ${esc(ago(k.backed_up))}.` : "Not backed up yet."}` : ""}</div>
      ${never ? `<div class="sub bad">Never backed up: ${rnSignBackup ? "download a copy and keep it offline"
        : "an administrator on this project downloads a copy to keep offline"}, since losing it is final.</div>` : ""}
      ${retired ? `<div class="sub">Retired: rotated to ${esc(k.retired_for)}. Kept, since the proof and every device before Android 9 still need it.</div>` : ""}
      ${rotated ? `<div class="sub">Rotated from ${esc(k.rotated_from)}: Android 9 and newer see this key, older devices still see ${esc(k.rotated_from)}.</div>` : ""}
      ${rnSignPw[`${key}:${route}`] ? `<div class="rnsignbar">
        <input type="password" data-signbackuppass autocomplete="current-password" placeholder="the backup password" aria-label="the backup password">
        <button type="button" class="link" data-signbackupgo>Download</button></div>` : ""}
      ${d.open ? `<div class="rnsignform">
        <input type="file" data-signfile accept=".jks,.p12,.pfx,.keystore" aria-label="${esc(word)} keystore">
        <input type="password" data-signpass autocomplete="new-password" placeholder="keystore password" aria-label="keystore password">
        <input data-signalias autocomplete="off" spellcheck="false" placeholder="alias, when it holds several" aria-label="key alias">
        <input type="password" data-signkeypass autocomplete="new-password" placeholder="key password, if not the same" aria-label="key password">
      </div>` : ""}
      <div class="rnsignbar">
        ${rnSignLocked || d.open ? `<button type="button" class="link" data-signopen>${d.open ? "Never mind" : k ? "Replace" : "Upload one"}</button>` : ""}
        ${!k && !d.open && rnSignTool && rnSignLocked ? `<button type="button" class="link" data-signgen>Generate</button>` : ""}
        ${k && rnSignBackup ? (rnSignLocked
          ? `<button type="button" class="link" data-signbackuppw>Download backup</button>`
          : `<a class="link" data-signbackup href="/api/signing-backup?project=${encodeURIComponent(name)}&key=${encodeURIComponent(key)}&route=${route}" download>Download backup</a>`) : ""}
        ${k ? `
        ${retired ? "" : `<button type="button" class="link" data-signremove>${d.remove ? "Keep it after all" : "Remove"}</button>`}` : ""}
        ${targets.length ? `<select data-rotateto aria-label="the key to rotate ${esc(key)} to">${
          targets.map(n => `<option>${esc(n)}</option>`).join("")}</select>
        <button type="button" class="link" data-rotate>Rotate to it</button>` : ""}
      </div>
    </div>`;
  };
  const maps = {...rnSignMap, ...rnSignMapDraft};
  // The backup password (the operator, 1 Oct): the project's owner's to set,
  // and every download's to give, BuilderBot's owner's included.
  const lockRow = `<div class="rnsign rnsignlock">
      <div>Backup password: ${rnSignLocked ? "set" : "none"}</div>
      <div class="sub dim">${rnSignLocked ? "Every key backup asks for it, whoever downloads it."
        : "Every key backup will ask for it, whoever downloads it."}${rnSignMayLock ? "" : " The project's owner sets it."}</div>
      ${rnSignLocked ? "" : `<div class="sub bad">No key can be added or made until it has one${rnSignMayLock ? ": set it first" : ""}.</div>`}
      ${rnSignMayLock && rnSignLockOpen ? `<div class="rnsignform">
        ${rnSignLocked ? `<input type="password" id="rnLockCur" autocomplete="current-password" placeholder="the backup password now" aria-label="the backup password now">` : ""}
        <input type="password" id="rnLockNew" autocomplete="new-password" placeholder="${rnSignLocked ? "a new one, or empty to remove it" : "at least ten characters"}" aria-label="the new backup password">
        <input type="password" id="rnLockAgain" autocomplete="new-password" placeholder="the new one again" aria-label="the new backup password again">
        <div class="rnsignbar"><button type="button" class="link" id="rnLockGo">${rnSignLocked ? "Change it" : "Set it"}</button></div>
      </div>` : ""}
      ${rnSignMayLock ? `<div class="rnsignbar"><button type="button" class="link" id="rnLockOpen">${
        rnSignLockOpen ? "Never mind" : rnSignLocked ? "Change or remove" : "Set a backup password"}</button></div>` : ""}
    </div>`;
  $("rnSignRows").innerHTML = lockRow + names.map(key => `<div class="rnsignkey">
      <div class="rnsignname">${key === "default" ? "Default key" : `Key: ${esc(key)}`}</div>
      ${RN_SIGN.map(([route, word, about]) => slot(key, route, word, about)).join("")}</div>`).join("")
    + `<div class="rnsignbar"><input id="rnSignNewName" autocomplete="off" spellcheck="false" placeholder="name, e.g. watch"
         aria-label="a new key's name"><button type="button" class="link" id="rnSignNewGo">New key</button></div>
    <div class="rnsignname">Apps</div>
    <div class="sub dim">Which app signs with which key, by its package; one not listed signs with the default key.</div>
    ${Object.entries(maps).filter(([, k]) => k !== null).map(([pkg, k]) => `<div class="rninvite" data-pkg="${esc(pkg)}">
      <code>${esc(pkg)}</code> <span class="dim">signs with</span> <b>${esc(k)}</b>
      <button type="button" class="link" data-unmap>Remove</button></div>`).join("")}
    <div class="rninvitebar"><input id="rnMapPkg" autocomplete="off" spellcheck="false" placeholder="com.example.app"
        aria-label="an app's package"><select id="rnMapKey" aria-label="the key it signs with">${
        names.map(k => `<option>${esc(k)}</option>`).join("")}</select>
      <button type="button" class="link" id="rnMapGo">Map it</button></div>`;
  $("rnSignHint").textContent = rnSignTool ? ""
    : "No keytool here to check or make a key with: install the jdk toolchain, then add one.";
  for (const row of $("rnSignRows").querySelectorAll(".rnsign[data-key]")){
    const key = row.dataset.key, route = row.dataset.route;
    const d = rnSignDraft[`${key}:${route}`] = rnSignDraft[`${key}:${route}`] || {key, route};
    const op = row.querySelector("[data-signopen]");
    if (op) op.onclick = () => {
      d.open = !d.open;
      if (!d.open){ delete d.file; d.pass = d.alias = d.keypass = ""; }
      else d.remove = false;
      rnDrawSigning();
    };
    const gen = row.querySelector("[data-signgen]");
    if (gen) gen.onclick = async () => {
      if (route === "sideload" && !confirm(`Make a new sideload signing key named ${key}? `
            + "Once a build signed with it is out, it is that app's identity for good: download a backup straight after."))
        return;
      gen.disabled = true;
      const j = await (await postJSON("/api/signing", {action: "generate", project: name, key, route})).json();
      if (j.error){ gen.disabled = false; return notify(j.error, true); }
      notify(`${key}: a ${route === "play" ? "Play upload" : "sideload signing"} key was made; download a backup`);
      rnSignNew = rnSignNew.filter(n => n !== key);
      rnLoadSigning(name);
    };
    const rot = row.querySelector("[data-rotate]");
    if (rot) rot.onclick = async () => {
      const to = row.querySelector("[data-rotateto]").value;
      if (!confirm(`Rotate ${key}'s sideload key to ${to}? Builds then go out signed with both and a proof: `
            + `Android 9 and newer move to ${to}, older devices keep checking ${key}, and ${key} is kept for good.`)) return;
      rot.disabled = true;
      const j = await (await postJSON("/api/signing", {action: "rotate", project: name, from: key, to})).json();
      if (j.error){ rot.disabled = false; return notify(j.error, true); }
      notify(`${key} is rotated to ${to}: the apps it signed now sign with ${to} and the proof`);
      rnLoadSigning(name);
    };
    const rm = row.querySelector("[data-signremove]");
    if (rm) rm.onclick = () => { d.remove = !d.remove; if (d.remove){ d.open = false; delete d.file; } rnDrawSigning(); };
    const bp = row.querySelector("[data-signbackuppw]");
    if (bp) bp.onclick = () => { rnSignPw[`${key}:${route}`] = !rnSignPw[`${key}:${route}`]; rnDrawSigning(); };
    const bg = row.querySelector("[data-signbackupgo]");
    if (bg) bg.onclick = async () => {
      const pw = row.querySelector("[data-signbackuppass]").value;
      bg.disabled = true;
      const r = await postJSON("/api/signing-backup", {project: name, key, route, password: pw});
      if (!r.ok){ bg.disabled = false; return notify((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`, true); }
      const fname = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || `${name}-${key}-${route}`;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await r.blob()); a.download = fname;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      delete rnSignPw[`${key}:${route}`];
      rnLoadSigning(name);
    };
    const bk = row.querySelector("[data-signbackup]");
    if (bk) bk.onclick = () => setTimeout(() => rnLoadSigning(name), 1500);
    const f = row.querySelector("[data-signfile]");
    if (f){
      f.onchange = () => { d.file = f.files[0] || null; };
      for (const [sel, k] of [["[data-signpass]", "pass"], ["[data-signalias]", "alias"], ["[data-signkeypass]", "keypass"]]){
        const el = row.querySelector(sel);
        el.value = d[k] || "";
        el.oninput = () => { d[k] = el.value; };
      }
    }
  }
  const lo = $("rnLockOpen");
  if (lo) lo.onclick = () => { rnSignLockOpen = !rnSignLockOpen; rnDrawSigning(); };
  const lg = $("rnLockGo");
  if (lg) lg.onclick = async () => {
    const cur = $("rnLockCur")?.value || "", nw = $("rnLockNew").value, again = $("rnLockAgain").value;
    if (nw !== again) return notify("the two new passwords differ", true);
    if (!nw && !rnSignLocked) return notify("type a password to set", true);
    lg.disabled = true;
    const j = await (await postJSON("/api/signing", {action: "backup-password", project: name, current: cur, new: nw})).json();
    if (j.error){ lg.disabled = false; return notify(j.error, true); }
    notify(j.backup_locked ? `${projLabel(name)}'s key backups now ask for the password` : `${projLabel(name)}'s key backups no longer ask for a password`);
    rnSignLockOpen = false;
    rnLoadSigning(name);
  };
  $("rnSignNewGo").onclick = () => {
    const n = $("rnSignNewName").value.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]{0,31}$/.test(n)) return notify("a key's name is lowercase letters, digits and dashes", true);
    if (!names.includes(n)) rnSignNew.push(n);
    rnDrawSigning();
  };
  $("rnMapGo").onclick = () => {
    const pkg = $("rnMapPkg").value.trim();
    if (!/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$/.test(pkg)) return notify("a package name looks like com.example.app", true);
    rnSignMapDraft[pkg] = $("rnMapKey").value;
    rnDrawSigning();
  };
  $("rnSignRows").querySelectorAll("[data-unmap]").forEach(b => b.onclick = () => {
    const pkg = b.closest("[data-pkg]").dataset.pkg;
    if (rnSignMap[pkg]) rnSignMapDraft[pkg] = null; else delete rnSignMapDraft[pkg];
    rnDrawSigning();
  });
}

const fileB64 = f => new Promise((ok, bad) => {
  const r = new FileReader();
  r.onload = () => ok(String(r.result).split(",")[1] || "");
  r.onerror = () => bad(r.error);
  r.readAsDataURL(f);
});

// What the draft changes, for Save: uploads, removals and mappings.
const rnSignPending = () => Object.values(rnSignDraft).some(d => d.remove || d.file)
  || Object.keys(rnSignMapDraft).length > 0;

// The draft's writes, in Save's order; "" when they all landed, else why.
async function rnSaveSigning(name){
  for (const d of Object.values(rnSignDraft)){
    const word = (RN_SIGN.find(([r]) => r === d.route) || [])[1] || d.route;
    let body = null;
    if (d.remove) body = {action: "remove", project: name, key: d.key, route: d.route};
    else if (d.file) body = {action: "put", project: name, key: d.key, route: d.route, keystore: await fileB64(d.file),
                             password: d.pass || "", alias: (d.alias || "").trim(), key_password: d.keypass || ""};
    if (!body) continue;
    const j = await (await postJSON("/api/signing", body)).json();
    if (j.error) return `${d.key} ${word}: ${j.error}`;
  }
  for (const [pkg, key] of Object.entries(rnSignMapDraft)){
    const j = await (await postJSON("/api/signing", {action: "map", project: name, package: pkg, key: key || ""})).json();
    if (j.error) return `${pkg}: ${j.error}`;
  }
  return "";
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
      rnBars();
    })
    .catch(() => {});                          // the rename itself still works
}

// The project's own deploy key (the operator, 12 Oct): made or pasted here,
// shown by its public half with where the host takes it, forgotten here.
// Shown wherever the token is: a project that may push.
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
  for (const [id, mode] of [["rnAuthNone", "none"], ["rnAuthKey", "ssh"],
                            ["rnAuthToken", "https"]]){
    const on = rnAuthPick === mode;
    $(id).classList.toggle("on", on);
    $(id).setAttribute("aria-checked", on ? "true" : "false");
  }
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
const RN_SECTS = ["project", "repo", "runs", "files", "sees", "build", "signing", "claude", "yours"];
// Which section each of rnPrefWas's fields is in, and what it is called.
const RN_WAS = {
  color: ["project", "Color"],
  node: ["runs", "Node"], nodes: ["runs", "Node"], hosts: ["runs", "Hosts its containers on"], gpu: ["runs", "The node's GPU"], tests_in: ["runs", "Where tests run"],
  reads: ["sees", "Reads"], sees: ["sees", "Also sees"], reaches: ["sees", "Also reaches"], debug: ["sees", "Debugging"],
  build: ["build", "Build"], test: ["build", "Test"], outputs: ["build", "Outputs"],
  capture_days: ["build", "Captures kept"], snapshot_days: ["build", "Snapshots kept"], dev_keep: ["build", "Dev builds kept"],
  gate: ["claude", "Claude may"], test_change: ["claude", "During a test run, a change asked for"],
  devbuild: ["claude", "Claude may"], report: ["claude", "Claude may"], sign: ["claude", "Claude may"],
  keys: ["claude", "Claude may"], release: ["claude", "Claude may"], version: ["claude", "Move the version"],
  reply: ["yours", "Replies"], asks: ["yours", "Questions"],
  git_name: ["yours", "Commit name and email"], git_email: ["yours", "Commit name and email"],
};
// What a running session takes only when it starts (the briefing, the launch
// flags, the view it runs in); everything else is read when it is used.
const RN_AT_START = new Set(["reply", "asks", "git_name", "git_email", "node", "nodes",
                             "reads", "sees", "test_change", "gpu", "capture_days", "snapshot_days", "dev_keep"]);

// The fields as they stand, in rnPrefWas's own shape, so each compares with
// its saved value directly.
function rnEnc(){
  // The node pickers are drawn once the node list has arrived: until then
  // they say nothing, and reading them as a change woke the Where it runs
  // bar on every open under load (the gate, 10 Oct).
  const drawn = nodesList !== null;
  const node = drawn ? $("rnNode").value : rnPrefWas.node;
  const dbg = $("rnDebugField").hidden ? null : rnDebugNow();
  return {git_name: $("rnGitName").value.trim(), git_email: $("rnGitEmail").value.trim(),
          node, nodes: !drawn ? rnPrefWas.nodes
            : (node ? [node, ...[...$("rnNodesMore").querySelectorAll("input:checked")].map(i => i.value).filter(id => !rnHostIds().has(id))] : []).join(","),
          // The ticked rows marked Hosting only are prefs.hosts, the rest
          // prefs.nodes: one list on screen, two settings underneath.
          hosts: !drawn ? rnPrefWas.hosts : [...$("rnNodesMore").querySelectorAll("input:checked")].map(i => i.value).filter(id => rnHostIds().has(id)).join(","),
          reads: [...$("rnReads").querySelectorAll("input:checked")].map(i => i.value).join(","),
          sees: $("rnSees").value.split(",").map(x => x.trim()).filter(Boolean).join(", "),
          reaches: JSON.stringify(rnReachNow()),
          debug: dbg ? rnDebugKey(dbg.diag, dbg.log_from) : rnPrefWas.debug,
          build: $("rnBuildCmd").value.trim(), test: $("rnTestCmd").value.trim(),
          outputs: $("rnOutputs").value.trim(),
          capture_days: $("rnCaptureDays").value.trim(), snapshot_days: $("rnSnapDays").value.trim(),
          dev_keep: $("rnDevKeep").value.trim(), gate: gateKey(rnGateNow()),
          tests_in: $("rnDevTest").value || "node", test_change: $("rnTestChange").value || "wait",
          gpu: $("rnGpu").value || "on", reply: $("rnReply").value || "", asks: $("rnAsks").value || "",
          devbuild: $("rnGateDocker").value || "deny", report: $("rnGateReport").value || "auto",
          sign: $("rnGateSign").value || "ask", release: $("rnGateRelease").value || "ask",
          keys: $("rnGateKeys").value || "ask", version: $("rnGateVersion").value || "locked",
          color: rnColorNow()};
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
  if (sect === "signing" && rnSignPending()) said.push("Signing keys");
  return {said, start};
}

const rnDirty = () => RN_SECTS.filter(s => rnSectChanges(s).said.length);

// The bars, put in once and then kept in step with what is typed: dead
// rather than gone while there is nothing to save, so nothing moves under a
// thumb (sectBar's rule).
function rnBars(){
  if (rnFor === null) return;
  const enc = rnEnc(), running = liveSessions().has(myClaude(rnFor));
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
    // A remote it can only read has nothing here to save (rnGitNone).
    bar.parentElement.hidden = sect === "repo" && !$("rnGitNone").hidden;
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
    rnFillColor(w.color);
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
  } else if (sect === "sees"){
    rnFillReads();
    $("rnSees").value = w.sees;
    $("rnReachRows").innerHTML = "";
    rnReachDraft = JSON.parse(w.reaches || "[]");
    rnDrawReach();
    rnFillDebug();
    const on = new Set(String(w.debug).replace(/^diag;/, "").split(",").filter(Boolean));
    $("rnDebug").querySelectorAll("input").forEach(i => {
      i.checked = i.value === "@diag" ? String(w.debug).startsWith("diag;") : on.has(i.value); });
  } else if (sect === "build"){
    $("rnBuildCmd").value = w.build; $("rnTestCmd").value = w.test; $("rnOutputs").value = w.outputs;
    $("rnCaptureDays").value = w.capture_days; $("rnSnapDays").value = w.snapshot_days;
    $("rnDevKeep").value = w.dev_keep;
  } else if (sect === "signing"){
    rnSignDraft = {}; rnSignMapDraft = {}; rnSignNew = []; rnDrawSigning();
  } else if (sect === "claude"){
    const g = String(w.gate).split(",");
    Object.values(GATE_IDS).forEach((id, i) => { $(id).value = g[i] || "auto"; });
    $("rnTestChange").value = w.test_change; $("rnGateDocker").value = w.devbuild;
    $("rnGateReport").value = w.report; $("rnGateSign").value = w.sign;
    $("rnGateRelease").value = w.release; $("rnGateKeys").value = w.keys;
    $("rnGateVersion").value = w.version;
  } else if (sect === "yours"){
    $("rnReply").value = w.reply; $("rnAsks").value = w.asks;
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
  const dk = String(w.debug || "");
  const g = String(w.gate || "").split(",");
  return {...w,
    nodes: String(w.nodes || "").split(",").filter(Boolean),
    hosts: String(w.hosts || "").split(",").filter(Boolean),
    reads: String(w.reads || "").split(",").filter(Boolean),
    sees: String(w.sees || "").split(",").map(x => x.trim()).filter(Boolean),
    reaches: JSON.parse(w.reaches || "[]"),
    dbg: $("rnDebugField").hidden ? null
      : {diag: dk.startsWith("diag;"), log_from: dk.replace(/^diag;/, "").split(",").filter(Boolean)},
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
  const merged = {...rnPrefWas, ...Object.fromEntries(mine.map(k => [k, enc[k]]))};
  const v = rnDec(merged);
  const {start} = rnSectChanges(sect, enc);
  const prefsChanged = mine.some(k => k !== "version" && String(enc[k] ?? "") !== String(rnPrefWas[k] ?? ""));
  const running = liveSessions().has(myClaude(name));
  // The name and the remote are their own sections' alone.
  const to = sect === "project" ? $("rnName").value : projLabel(name);
  const token = sect === "repo" ? $("rnToken").value.trim() : "";
  const auth = sect === "repo" && rnAuthPick && rnAuthPick !== rnAuthNow ? rnAuthPick : "";
  const clear_token = sect === "repo" && rnClearToken && !token;
  const addrNow = $("rnAddr").value.trim();
  const address = sect === "repo" && !$("rnAddrField").hidden && rnAuthOpts?.url && addrNow && addrNow !== rnAuthOpts.url
    ? addrNow : "";
  if (!to.trim()) return fail("a new name is needed");
  if (sect === "signing"){
    if (Object.values(rnSignDraft).some(d => d.open && !d.file && (d.pass || d.alias)))
      return fail("pick the keystore file for the key whose password you typed");
    if (Object.values(rnSignDraft).some(d => d.file && !d.pass))
      return fail("type the keystore's password: a key is checked with it before it is kept");
  }
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
      const r = await fetch("/api/prefs", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({project: name, git_name: v.git_name, git_email: v.git_email,
                              node: v.node, nodes: v.nodes, hosts: v.hosts, reads: v.reads, sees: v.sees, reaches: v.reaches,
                              build: v.build, test: v.test, gate: v.gate, color: v.color, ...(v.dbg || {}),
                              tests_in: v.tests_in, test_change: v.test_change, gpu: v.gpu, reply: v.reply, asks: v.asks,
                              devbuild: v.devbuild, report: v.report, sign: v.sign, keys: v.keys, release: v.release,
                              outputs: v.outputs.split(",").map(x => x.trim()).filter(Boolean),
                              ...(v.capture_days !== "" ? {capture_days: +v.capture_days} : {}),
                              ...(v.snapshot_days !== "" ? {snapshot_days: +v.snapshot_days} : {}),
                              ...(v.dev_keep !== "" ? {dev_keep: +v.dev_keep} : {}),
                              restart: restartNow})});
      const j = await r.json();
      if (j.error) return stop(j.error);
      // Said out loud when the session was left on what it started with,
      // and why, and when it was ended.
      if (running && start.length && !j.ended)
        notify(restartNow
                 ? `${projLabel(name)}: saved, but the session was not ended: ` + (j.why || "it is still on what it started with")
                 : `${projLabel(name)}: saved. Its running session keeps what it started with until you end it and press Claude again.`,
               restartNow);
      else if (restartNow && j.ended)
        notify(`${projLabel(name)}: saved, and its session ended: press Claude to start one on it, resuming the conversation`);
    }
    if (sect === "project" && rnPeople && ((rnPeopleDraft.owner && rnPeopleDraft.owner !== rnPeople.owner)
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
    if (sect === "signing" && rnSignPending()){
      const why = await rnSaveSigning(name);
      if (why) return stop(why);
      notify(`${projLabel(name)}: signing keys saved`);
      rnLoadSigning(name);
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
  if (!confirm(`Delete ${projLabel(name)}?\n\n`
      + `It moves to /workspace/.trash/${name}, with every file kept. Its `
      + `roadmap, bugs, versions, memories and containers stay where they are, `
      + `and Put back in the trash returns all of it.\n\n`
      + `Close its terminals first, and bring its dev instance down.`)) return;
  try{
    const r = await postJSON("/api/trash", {name});
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    // The path is named back because it may not be the one the dialog said:
    // a second delete of the same name is numbered rather than overwriting the
    // first, and the first is exactly the copy somebody would want back.
    notify(`${projLabel(name)} moved to ${j.to}`);
  }catch(e){ notify("delete failed: " + e, true); }
  refresh();
}
