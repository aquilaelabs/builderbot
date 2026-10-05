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
// What Claude's default here actually IS, read from the last transcript
// when the dialog opens: with nothing set the picker used to read "leave
// as is", which says nothing, and choosing the model the session was
// already on counted as a change and asked to restart it. The picker now
// shows that model, and picking it is picking the default.
let rnModelNow = "";
const rnModelPick = () => {
  const v = $("rnModel").value;
  return rnPrefWas.model === "" && v === rnModelNow ? "" : v;
};
function rnLoadModelNow(name){
  rnModelNow = "";
  fetch(`/api/claude-now?project=${encodeURIComponent(name)}`)
    .then(r => r.json())
    .then(j => {
      if (rnFor !== name || !j.model) return;
      rnModelNow = j.model;
      if (rnPrefWas.model === "" && MODELS.some(([v]) => v === j.model)){
        $("rnModel").value = j.model;
        rnDrawPrefs();
      }
    })
    .catch(() => {});
}

// What the dialog was opened showing, so Save can tell a real change from a
// dialog that was merely looked at: the difference decides whether a running
// session is restarted, which is not something to do because somebody opened
// a menu.
let rnPrefWas = {model: "", effort: "", git_name: "", git_email: "",
                 node: "", nodes: "", reads: "", sees: "", build: "", test: "", outputs: "",
                 capture_days: "7", dev_keep: "3", gate: "", color: ""};
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
  rnPrefWas = {model: p?.yours?.model || "", effort: p?.yours?.effort || "",
               git_name: p?.yours?.git_name || "", git_email: p?.yours?.git_email || "",
               node: p?.prefs?.node || "",
               nodes: (p?.prefs?.nodes || []).join(","),
               reads: (p?.prefs?.reads || []).join(","),
               sees: (p?.prefs?.sees || []).join(", "),
               build: p?.prefs?.build || "", test: p?.prefs?.test || "",
               outputs: (p?.prefs?.outputs || []).join(", "),
               capture_days: String(p?.prefs?.capture_days ?? 7),
               dev_keep: String(p?.prefs?.dev_keep ?? 3),
               gate: gateKey(p?.prefs?.gate),
               tests_in: p?.prefs?.tests_in || "node",
               test_change: p?.prefs?.test_change || "wait",
               gpu: p?.prefs?.gpu || "on",
               reply: p?.yours?.reply || "", asks: p?.yours?.asks || "",
               devbuild: devClaudeMode(rnFor),
               report: p?.prefs?.report || "auto",
               sign: p?.prefs?.sign || "ask",
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
  rnFillNode();
  rnFillPrefsRest(p);
  rnFillReads();
  rnLoadModelNow(rnFor);
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
    const pick = (nodesList || []).filter(n => n.kind !== "local" && n.state !== "retired");
    if (nodesList === null){
      const opened = rnFor;
      loadNodes().then(() => { if (opened !== null && rnFor === opened) rnFillNode(); });
    }
    // Hidden with the rest of the project's own settings when this dialog was
    // opened by the chain, which asks about the remote and nothing else.
    wrap.hidden = rnMode === "git" || !pick.length;
    // Shown to everybody on the project and changed by grant (R137 step 4):
    // a node is shared, so the picker is read-only without `node`.
    sel.disabled = state?.can?.node === false;
    // The places a session is shown are places on a node, so the field is
    // there when a node is.
    $("rnSeesField").hidden = wrap.hidden;
    // What each node carries, on its own option: the node does everything
    // for this project, so the only question left is what is installed on it.
    const tools = n => Object.keys(n.reported?.toolchains || {});
    sel.innerHTML = `<option value="">none: no builds, tests or Claude sessions until one is picked</option>`
      + pick.map(n => `<option value="${esc(n.id)}"${n.id === rnPrefWas.node ? " selected" : ""}>${
          esc(n.name)} (${esc(n.kind)}, ${esc(n.state)}${n.live === false ? ", quiet" : ""}${
          tools(n).length ? " · " + esc(tools(n).slice(0, 4).join(", ")) : ""})</option>`).join("");
    sel.value = pick.some(n => n.id === rnPrefWas.node) ? rnPrefWas.node : "";
    rnFillNodesMore();
}

// A listbox row: a checkbox, the name, and a quiet note at the right.
const lrow = (value, name, sub, on) => `<label class="lrow"><input type="checkbox" value="${esc(value)}"${
    on ? " checked" : ""}><span>${esc(name)}</span>${sub ? `<span class="lsub">${esc(sub)}</span>` : ""}</label>`;

// The rest of the set (R82): every node but the primary, a listbox row each,
// ticked for the ones the project also works on. Redrawn when the primary
// changes, since the primary is never offered twice.
function rnFillNodesMore(){
  const box = $("rnNodesMore"), hint = $("rnNodesMoreHint"), label = $("rnNodesLabel");
  if (!box) return;
  const primary = $("rnNode").value;
  const was = new Set(rnPrefWas.nodes.split(",").filter(Boolean));
  const checked = new Set([...box.querySelectorAll("input:checked")].map(i => i.value));
  const first = !box.dataset.drawn;
  const others = (nodesList || []).filter(n => n.kind !== "local" && n.state !== "retired" && n.id !== primary);
  box.hidden = hint.hidden = label.hidden = rnMode === "git" || !primary || !others.length;
  box.innerHTML = others.map(n => lrow(n.id, n.name, `${n.kind}, ${n.state}${n.live === false ? ", quiet" : ""}`,
                                       first ? was.has(n.id) : checked.has(n.id))).join("");
  // Read-only without the `node` grant, like the primary above (R137 step 4).
  if (state?.can?.node === false) box.querySelectorAll("input").forEach(i => { i.disabled = true; });
  box.dataset.drawn = "1";
}

// The projects a session here may read: every other project this account
// sees, a listbox row each, ticked from the settings. Read-only there by
// construction (users.with_reads), so the hint under it can say so plainly.
function rnFillReads(){
  const box = $("rnReads"), wrap = $("rnReadsField");
  if (!box) return;
  const was = new Set(rnPrefWas.reads.split(",").filter(Boolean));
  const others = (state?.projects || []).filter(p => p.name !== rnFor)
    .sort((a, b) => a.name.localeCompare(b.name));
  wrap.hidden = rnMode === "git" || !others.length;
  box.innerHTML = others.map(p => lrow(p.name, p.name, p.branch ? `git: ${p.branch}` : "", was.has(p.name))).join("");
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
  for (const [id, table, cur] of [["rnModel", MODELS, rnPrefWas.model],
                                  ["rnEffort", EFFORTS, rnPrefWas.effort]]){
    const el = $(id);
    if (el.dataset.built !== "1"){
      el.innerHTML = table.map(([v, l]) =>
        `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = cur;
  }
  rnDrawPrefs();
}

function rnDrawPrefs(){
  const p = (state?.projects || []).find(x => x.name === rnFor);
  // Ghosted where no session can start: a locked project is the operator's to
  // run. Setting what a session that cannot exist would launch on is a control
  // with nothing behind it, and unlike the credential fields above, there is
  // no typing here that would bring it back.
  const shut = !!p?.locked;
  $("rnModel").disabled = $("rnEffort").disabled = shut;
  const running = liveSessions().has(myClaude(rnFor));
  const changed = rnModelPick() !== rnPrefWas.model
               || $("rnEffort").value !== rnPrefWas.effort;
  const dflt = rnPrefWas.model === "" && rnModelNow
    ? ` ${(MODELS.find(([v]) => v === rnModelNow) || [])[1] || rnModelNow} is Claude's `
      + `own default here.` : "";
  $("rnPrefHint").textContent = shut
    ? "Locked; this project is yours to run, so no session starts here."
    : running
      ? (changed
          ? "A session is running here. Save asks whether to end it now (the "
            + "conversation resumes from the Claude button) or keep it running."
          : "Applies when a session starts; changing it asks about the one running "
            + "here." + dflt)
      : "Applied the next time Claude starts here, and kept until you change it." + dflt;
  $("rnPrefHint").classList.toggle("bad", !shut && running && changed);
}

// ---- a project's settings dialog, wired ---------------------------------

// Unlinking asks, and the question lists what goes rather than asking twice:
// a stored token is not recoverable and a push grant frees the repository for
// another project. Nothing in the tree is touched, which is the half worth
// saying out loud; somebody pressing this is worried about their commits.
async function unlinkProject(name){
  const p = (state?.projects || []).find(x => x.name === name);
  const where = p?.forge_host || p?.forge_name || "its remote";
  if (!confirm(`Unlink ${name} from ${where}?\n\n`
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
    notify(`${name} is unlinked: ${(j.removed || []).join(", ")}`
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
// The answer to the question at the foot (rnRestartAsk): "end" or "keep"
// once one of its two buttons was pressed, null while it has not been asked.
let rnAsked = null;

// The question put away: on open, on close, and on a save that failed.
function rnAskReset(){
  rnAsked = null;
  $("rnRestartAsk").hidden = true;
  $("rnKeep").hidden = true;
}
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
  $("rnCancel").textContent = "Cancel";
}
function settingsInto(name, host){
  if (!host) return;
  renameProject(name);
  $("rnmodal").hidden = true;
  const box = $("rnmodal").querySelector(":scope > .box");
  if (box) host.appendChild(box);
  // A view, never a dialog to shut: whatever hid it is undone here.
  host.removeAttribute("hidden");
  rnHost = host;
  // In place there is nothing to cancel out of: Revert puts the fields back.
  $("rnCancel").textContent = "Revert";
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
  $("rnTitle").textContent = git ? `${where} settings for ${name}` : name;
  for (const id of ["rnNameField", "rnColorField", "rnMineField",
                    "rnGateField", "rnBuildField", "rnReadsField"])
    $(id).hidden = git;
  // The node picker and the two credential blocks have hidden rules of their
  // own further down, and each of those consults the mode too.
  $("rnName").value = name;
  $("rnToken").value = "";
  $("rnErrWrap").hidden = true;
  $("rnPreview").hidden = true;
  $("rnName").classList.remove("bad");
  // The warning about what a rename moves is shown once the name is
  // edited (rnShow), not to everyone opening the dialog for a setting.
  $("rnHint").textContent = "";
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
      `${name} has a remote it can only read, so there is no credential to set here.`;
  // Unlink is the chain's, never the gear's: it is about the remote, and it
  // is the way a project moves from one host to another, since linking
  // refuses a repo that already has one.
  $("rnUnlink").hidden = !(git && p?.linked);
  $("rnUnlink").textContent = `Unlink from ${p?.forge_name || "its remote"}`;
  // The bin, on the gear's door only: the chain's is about the remote.
  $("rnDelete").hidden = git || !p;
  rnLoadAuth(name);
  rnLoadSigning(name);
  rnLoadPeople(name);
  rnFillPrefs(p);
  // The sessions at the foot: the gear's door, and an administrator's.
  $("rnSessField").hidden = true;
  if (!git && state?.admin) rnSessionsLoad(name);
  $("rnGo").disabled = false;
  $("rnGo").textContent = "Save";
  rnAskReset();
  // Nothing to save is nothing to press: with no credential to set, Cancel is
  // the only honest way out of this door, but Unlink still is one.
  $("rnGo").hidden = !$("rnGitNone").hidden;
  $("rnmodal").hidden = false;
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
  if (!rnPeople) return;
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
    <div class="sub dim">${only
      ? "Administrators cannot add themselves or anybody else: people join by accepting an invitation."
      : "Any administrator can add people, themselves included."}${v.may_manage ? "" : " Its owner decides this."}</div>
    <div class="sub">On it: ${v.members.length ? v.members.map(esc).join(", ") : "nobody yet"}</div>
    ${v.invites.map(i => `<div class="rninvite">${esc(i.name)} <span class="dim">invited by ${esc(i.by || "somebody")} ${esc(ago(i.at))}</span>
      <button type="button" class="link" data-withdraw="${i.id}">Withdraw</button></div>`).join("")}
    ${v.may_invite && invitable.length ? `<div class="rninvitebar">
      <select id="rnInviteWho" aria-label="account to invite">${invitable.map(n => `<option>${esc(n)}</option>`).join("")}</select>
      <button type="button" id="rnInviteGo">Invite</button></div>` : ""}`;
  const o = $("rnOwner");
  if (o) o.onchange = () => { d.owner = o.value; rnDrawPeople(); };
  const io = $("rnInviteOnly");
  if (io && v.may_manage) io.onchange = () => { d.invite_only = io.checked; rnDrawPeople(); };
  const act = async body => {
    const j = await (await postJSON("/api/members", body)).json();
    if (j.error) return notify(j.error, true);
    rnPeople = j; rnDrawPeople();
  };
  const go = $("rnInviteGo");
  if (go) go.onclick = () => act({action: "invite", project: rnFor, name: $("rnInviteWho").value})
    .then(() => notify(`invited to ${rnFor}: they say yes or no from their bell`));
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
  if (j.offered) notify(`${name}: offered to ${j.offered}, who becomes its owner on accepting from their bell`);
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

function rnDrawSigning(){
  if (!rnSignKeys) return;
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
    notify(j.backup_locked ? `${name}'s key backups now ask for the password` : `${name}'s key backups no longer ask for a password`);
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
  $("rnAddrField").hidden = true;
  $("rnAddr").value = "";
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
      if (j.url) $("rnGo").hidden = false;
      rnDrawAuth();
    })
    .catch(() => {});                          // the rename itself still works
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

const rnAuthSet = m => { if (rnAuthPick === m) return; rnAuthPick = m; rnDrawAuth(); };

const RN_MOVES = "Renaming moves the project and everything named after it. Close its "
  + "terminals and bring its dev instance down first.";

function rnShow(){
  const raw = $("rnName").value, clean = projName(raw);
  $("rnHint").textContent = clean && clean !== rnFor ? RN_MOVES : "";
  const taken = clean && clean !== rnFor
                && (state?.projects || []).some(p => p.name === clean);
  $("rnName").classList.toggle("bad", !!taken);
  $("rnPreview").classList.toggle("bad", !!taken);
  $("rnPreview").hidden = !taken && (!raw.trim() || clean === raw.trim());
  $("rnPreview").textContent = taken
    ? `${clean} already exists under /workspace`
    : clean ? `Will be renamed to ${clean}`
    : "That leaves nothing to name a directory after";
}

function closeRename(){
  // In place, closing is reading again: the saved values, once the poll has
  // them (or Revert's, the ones it had).
  if (rnHost){
    const n = rnFor, h = rnHost;
    settingsOut();
    rnFor = null; rnAskReset();
    Promise.resolve(refresh()).finally(() => {
      if (h.isConnected && (state?.projects || []).some(p => p.name === n)) settingsInto(n, h);
    });
    return;
  }
  $("rnmodal").hidden = true; rnFor = null; rnAskReset();
}

async function rnSubmit(){
  const name = rnFor, to = $("rnName").value, token = $("rnToken").value.trim();
  // "" for "leave the remote alone", which is every save that is only a
  // rename: the server treats the field's absence and a no-op the same way,
  // but sending the current mode back would make every save a rewrite.
  const auth = rnAuthPick && rnAuthPick !== rnAuthNow ? rnAuthPick : "";
  // A typed token replaces rather than clears, so the two never both go: the
  // server would otherwise write one and delete it in the same request.
  const clear_token = rnClearToken && !token;
  // Sent only when it was changed: "" leaves the remote where it points.
  const addrNow = $("rnAddr").value.trim();
  const address = !$("rnAddrField").hidden && rnAuthOpts?.url && addrNow && addrNow !== rnAuthOpts.url
    ? addrNow : "";
  const model = rnModelPick(), effort = $("rnEffort").value;
  const node = $("rnNode").value;
  const nodes = node ? [node, ...[...$("rnNodesMore").querySelectorAll("input:checked")].map(i => i.value)] : [];
  const reads = [...$("rnReads").querySelectorAll("input:checked")].map(i => i.value);
  const sees = $("rnSees").value.split(",").map(x => x.trim()).filter(Boolean);
  const build = $("rnBuildCmd").value.trim(),
        test = $("rnTestCmd").value.trim(), outputs = $("rnOutputs").value.trim();
  const capture_days = $("rnCaptureDays").value.trim();
  const dev_keep = $("rnDevKeep").value.trim();
  const gate = rnGateNow();
  const color = rnColorNow();
  // With the node's group: nothing here restarts a session.
  const tests_in = $("rnDevTest").value || "node";
  const test_change = $("rnTestChange").value || "wait";
  const gpu = $("rnGpu").value || "on";
  const reply = $("rnReply").value || "", asks = $("rnAsks").value || "";
  const devbuild = $("rnGateDocker").value || "deny";
  const report = $("rnGateReport").value || "auto";
  const sign = $("rnGateSign").value || "ask";
  const keys = $("rnGateKeys").value || "ask";
  const verPol = $("rnGateVersion").value || "locked";
  const nodeChanged = node !== rnPrefWas.node || nodes.join(",") !== rnPrefWas.nodes || build !== rnPrefWas.build
    || reads.join(",") !== rnPrefWas.reads || sees.join(", ") !== rnPrefWas.sees
    || test !== rnPrefWas.test || outputs !== rnPrefWas.outputs || capture_days !== rnPrefWas.capture_days
    || dev_keep !== rnPrefWas.dev_keep
    || gateKey(gate) !== rnPrefWas.gate || color !== rnPrefWas.color
    || tests_in !== rnPrefWas.tests_in || test_change !== rnPrefWas.test_change
    || gpu !== rnPrefWas.gpu
    || devbuild !== rnPrefWas.devbuild
    || report !== rnPrefWas.report
    || sign !== rnPrefWas.sign
    || keys !== rnPrefWas.keys;
  const git_name = $("rnGitName").value.trim(), git_email = $("rnGitEmail").value.trim();
  // Yours, so they travel with the model and the effort rather than with the
  // project's group: the same request, a different store on the server.
  const prefChanged = model !== rnPrefWas.model || effort !== rnPrefWas.effort
    || reply !== rnPrefWas.reply || asks !== rnPrefWas.asks
    || git_name !== rnPrefWas.git_name || git_email !== rnPrefWas.git_email;
  // What a running session takes only when it starts, named as the dialog
  // labels it: the launch flags (model, effort), the author it commits as
  // and the briefing it is handed (replies, questions, how a test run
  // meets a change, how long captures are kept), the node it runs on, and
  // the view it runs in (reads, sees). Everything else here is read when
  // it is used (the build and test commands, the dials, where tests run),
  // so a change to those reaches a running session without a restart.
  const takesAtStart = [
    [model !== rnPrefWas.model, "Model"], [effort !== rnPrefWas.effort, "Effort"],
    [reply !== rnPrefWas.reply, "Replies"], [asks !== rnPrefWas.asks, "Questions"],
    [git_name !== rnPrefWas.git_name || git_email !== rnPrefWas.git_email, "Commit name and email"],
    [node !== rnPrefWas.node || nodes.join(",") !== rnPrefWas.nodes, "Node"],
    [reads.join(",") !== rnPrefWas.reads, "Reads"], [sees.join(", ") !== rnPrefWas.sees, "Also sees"],
    [test_change !== rnPrefWas.test_change, "During a test run, a change asked for"],
    [gpu !== rnPrefWas.gpu, "The node's GPU"],
    [capture_days !== rnPrefWas.capture_days, "Captures kept"],
    [dev_keep !== rnPrefWas.dev_keep, "Dev builds kept"],
  ].filter(([changed]) => changed).map(([, label]) => label);
  const launchChanged = takesAtStart.length > 0;
  const running = liveSessions().has(myClaude(name));
  const fail = m => ($("rnErr").textContent = m, $("rnErrWrap").hidden = false);
  if (!to.trim()) return fail("a new name is needed");
  const signDraft = rnSignPending() ? [1] : [];
  if (Object.values(rnSignDraft).some(d => d.open && !d.file && (d.pass || d.alias)))
    return fail("pick the keystore file for the key whose password you typed");
  if (Object.values(rnSignDraft).some(d => d.file && !d.pass))
    return fail("type the keystore's password: a key is checked with it before it is kept");
  if (capture_days !== "" && !/^\d{1,3}$/.test(capture_days))
    return fail("captures kept is a number of days, 0 to 365");
  if (dev_keep !== "" && !/^\d{1,2}$/.test(dev_keep))
    return fail("dev builds kept is a number of builds, 0 to 99");
  // The one combination the dialog will not write: authenticating with a token
  // it is being told to throw away. The hint has been saying so; this is what
  // makes it true rather than advice.
  if (rnAuthPick === "https" && !((rnAuthOpts?.token && !rnClearToken) || token))
    return fail("pick a credential that will exist: there will be no access "
                + "token after this save");
  // Asked before anything is written, and only when it costs something: a
  // session that is not running has nothing to interrupt, and a dialog that
  // was opened and closed unchanged should never ask at all.
  //
  // The answer decides the RESTART and nothing else. It used to decide the
  // save as well (declining returned before anything was written) so
  // somebody who wanted the setting kept and the conversation left alone got
  // neither: the dialog stayed open looking unsaved, the setting never
  // landed, and restarting the session by hand afterwards changed nothing,
  // because there was nothing to read. Saving and interrupting are two
  // decisions and only one of them was being asked about.
  //
  // Asked in the dialog itself, naming the changes, with the two answers
  // in the foot (the operator, 29 Sep): the first press of Save shows the
  // question and saves nothing; the press that answers it saves.
  let restartNow = false;
  if (launchChanged && running){
    if (rnAsked === null){
      $("rnRestartWhat").textContent = `Changed: ${takesAtStart.join(", ")}.`;
      $("rnRestartAsk").hidden = false;
      $("rnKeep").hidden = false;
      $("rnGo").textContent = "Save and end it";
      $("rnRestartAsk").scrollIntoView({block: "nearest"});
      return;
    }
    restartNow = rnAsked === "end";
  }
  // Only what actually changed goes to the server. A rename request is
  // refused outright while a terminal is open, so a settings-only save must
  // not make one: it would fail on a project you were sitting in.
  const renaming = to.trim() !== name;
  const needRename = renaming || !!token || !!auth || clear_token || !!address;
  $("rnGo").disabled = true; $("rnGo").textContent = "Saving…";
  const stop = m => { $("rnGo").disabled = false; $("rnGo").textContent = "Save";
                      rnAskReset(); return fail(m); };
  try{
    if (prefChanged || nodeChanged){
      const r = await fetch("/api/prefs", {method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({project: name, model, effort, git_name, git_email,
                              node, nodes, reads, sees, build, test, gate, color,
                              tests_in, test_change, gpu, reply, asks, devbuild, report, sign, keys,
                              outputs: outputs.split(",").map(x => x.trim()).filter(Boolean),
                              ...(capture_days !== "" ? {capture_days: +capture_days} : {}),
                              ...(dev_keep !== "" ? {dev_keep: +dev_keep} : {}),
                              // The node binding never restarts a session;
                              // it is about containers, not the conversation.
                              restart: restartNow})});
      const j = await r.json();
      if (j.error) return stop(j.error);
      // Said out loud when it did not happen, and which of the two reasons it
      // is: a session quietly left on the old model is exactly the confusion
      // this whole thing exists to remove, and a session deliberately left
      // running is not a fault to color red.
      if (running && launchChanged && !j.ended)
        notify(restartNow
                 ? `${name}: saved, but the session was not ended: `
                   + (j.why || "it is still on what it started with")
                 : `${name}: saved. Its running session keeps what it started `
                   + `with until you end it and press Claude again.`,
               restartNow);
      else if (restartNow && j.ended)
        notify(`${name}: saved, and its session ended: press Claude to start `
               + `one on it, resuming the conversation`);
    }
    const peopleChanged = !!rnPeople && ((rnPeopleDraft.owner && rnPeopleDraft.owner !== rnPeople.owner)
      || (rnPeopleDraft.invite_only !== undefined && rnPeopleDraft.invite_only !== rnPeople.invite_only));
    if (peopleChanged){
      const why = await rnSavePeople(name);
      if (why) return stop(why);
    }
    // Move the version is version.py's policy: written where the Artifacts
    // tab writes it, so the two never disagree.
    if (verPol !== rnPrefWas.version){
      const j = await (await postJSON("/api/version", {project: name, action: "policy", policy: verPol})).json();
      if (j.error) return stop(j.error);
    }
    if (signDraft.length){
      const why = await rnSaveSigning(name);
      if (why) return stop(why);
      notify(`${name}: signing keys saved`);
    }
    if (!needRename){
      closeRename();
      if (!prefChanged && !nodeChanged && !signDraft.length && !peopleChanged
          && verPol === rnPrefWas.version) return;   // nothing changed
      refresh();
      return;
    }
    const r = await postJSON("/api/rename", {name, to, token, auth, clear_token, address});
    const j = await r.json();
    if (j.error) return stop(j.error);
    closeRename();
    // Named rather than assumed: sanitizing may have changed what was typed,
    // and the operator should see the name that actually exists.
    notify(j.failed?.length
      ? `${name} is now ${j.name}, but ${j.failed.length} thing(s) did not `
        + `move: ${j.failed.join("; ")}`
      : renaming ? `${name} is now ${j.name}`
      : address ? `${name}: ${(j.moved || []).find(m => /points at/.test(m)) || "saved"}`
      : `${name} saved`,
      !!j.failed?.length);
  }catch(e){ return stop("save failed: " + e); }
  refresh();
}

// Deleting asks once and says where the files go, rather than asking twice or
// making somebody type the name. The roadmap item this came from called for a
// typed confirmation, on the reasoning that it would be the one control here
// destroying work outside /config, and it is not that any more: the directory
// is moved to /workspace/.trash with everything in it, and the notebook is not
// touched at all. Putting one back is a mv. Friction proportionate to a
// reversible act, and the dialog names the path so the reversal is obvious.
async function deleteProject(name){
  if (!confirm(`Delete ${name}?\n\n`
      + `It moves to /workspace/.trash/${name}, with every file kept. Its `
      + `roadmap, bugs, versions and memories stay where they are.\n\n`
      + `Close its terminals first, and bring its dev instance down.`)) return;
  try{
    const r = await postJSON("/api/trash", {name});
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    // The path is named back because it may not be the one the dialog said:
    // a second delete of the same name is numbered rather than overwriting the
    // first, and the first is exactly the copy somebody would want back.
    notify(`${name} moved to ${j.to}`);
  }catch(e){ notify("delete failed: " + e, true); }
  refresh();
}
