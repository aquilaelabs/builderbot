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
                 node: "", nodes: "", reads: "", build: "", test: "", outputs: "",
                 capture_days: "7", gate: "", color: ""};
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
const GATE_IDS = {roadmap: "rnGateRoadmap", bugs: "rnGateBugs", rules: "rnGateRules", settings: "rnGateSettings",
                  design: "rnGateDesign"};
const rnGateNow = () => Object.fromEntries(
  Object.entries(GATE_IDS).map(([k, id]) => [k, $(id).value || "auto"]));
const gateKey = g => Object.keys(GATE_IDS).map(k => g?.[k] || "auto").join(",");

function rnFillPrefs(p){
  rnPrefWas = {model: p?.yours?.model || "", effort: p?.yours?.effort || "",
               git_name: p?.yours?.git_name || "", git_email: p?.yours?.git_email || "",
               node: p?.prefs?.node || "",
               nodes: (p?.prefs?.nodes || []).join(","),
               reads: (p?.prefs?.reads || []).join(","),
               build: p?.prefs?.build || "", test: p?.prefs?.test || "",
               outputs: (p?.prefs?.outputs || []).join(", "),
               capture_days: String(p?.prefs?.capture_days ?? 7),
               gate: gateKey(p?.prefs?.gate),
               tests_in: p?.prefs?.tests_in || "node",
               test_change: p?.prefs?.test_change || "wait",
               brief: p?.prefs?.brief || "full", reply: p?.yours?.reply || "", asks: p?.yours?.asks || "",
               devbuild: devClaudeMode(rnFor),
               report: p?.prefs?.report || "auto",
               color: p?.prefs?.color || ""};
  rnFillColor(rnPrefWas.color);
  $("rnGitName").value = rnPrefWas.git_name;
  $("rnGitEmail").value = rnPrefWas.git_email;
  // Said where it is typed: the Profile is the default, this is the exception,
  // and a commit needs both halves from somewhere.
  $("rnGitHint").textContent = rnPrefWas.git_name || rnPrefWas.git_email
    ? "Your commits here use these instead of your Profile."
    : "Empty uses your Profile. Set these to commit here under a different name.";
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
  $("rnBrief").value = p?.prefs?.brief || "full";
  $("rnReply").value = p?.yours?.reply || "";
  $("rnAsks").value = p?.yours?.asks || "";
  $("rnOutputs").value = (p?.prefs?.outputs || []).join(", ");
  $("rnCaptureDays").value = String(p?.prefs?.capture_days ?? 7);
  for (const [k, id] of Object.entries(GATE_IDS)){
    const el = $(id);
    if (el.dataset.built !== "1"){
      el.innerHTML = GATE_MODES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
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
    const el = $("rnGateDocker");
    if (el.dataset.built !== "1"){
      el.innerHTML = GATE_MODES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = devClaudeMode(rnFor);
    // An administrator's to change (docker-write), so not offered otherwise.
    el.closest("label").hidden = !state?.admin;
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
          ? "A session is running here. Saving restarts it onto this: the "
            + "conversation is resumed, but anything mid-turn is lost."
          : "Applies when a session starts; changing it restarts the one running "
            + "here, on the same conversation." + dflt)
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
let rnMode = "all";                      // "all" from the gear, "git" from the chain

function renameProject(name, mode = "all"){
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
  rnFillPrefs(p);
  // The sessions at the foot: the gear's door, and an administrator's.
  $("rnSessField").hidden = true;
  if (!git && state?.admin) rnSessionsLoad(name);
  $("rnGo").disabled = false;
  $("rnGo").textContent = "Save";
  // Nothing to save is nothing to press: with no credential to set, Cancel is
  // the only honest way out of this door, but Unlink still is one.
  $("rnGo").hidden = !$("rnGitNone").hidden;
  $("rnmodal").hidden = false;
}

// What the remote uses now, and what the operator has picked instead. Both
// null until this open's /api/project-auth answers: the dialog draws without
// them rather than waiting, so the token field is typeable before the request
// lands and the switch appears under it when it does.
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
  if (rnMode !== "git") return;
  fetch("/api/project-auth", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({name})})
    .then(r => r.json())
    .then(j => {
      if (rnFor !== name || j.error) return;   // closed, or reopened elsewhere
      rnAuthOpts = j;
      rnAuthNow = rnAuthPick = j.now || null;
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

function closeRename(){ $("rnmodal").hidden = true; rnFor = null; }

async function rnSubmit(){
  const name = rnFor, to = $("rnName").value, token = $("rnToken").value.trim();
  // "" for "leave the remote alone", which is every save that is only a
  // rename: the server treats the field's absence and a no-op the same way,
  // but sending the current mode back would make every save a rewrite.
  const auth = rnAuthPick && rnAuthPick !== rnAuthNow ? rnAuthPick : "";
  // A typed token replaces rather than clears, so the two never both go: the
  // server would otherwise write one and delete it in the same request.
  const clear_token = rnClearToken && !token;
  const model = rnModelPick(), effort = $("rnEffort").value;
  const node = $("rnNode").value;
  const nodes = node ? [node, ...[...$("rnNodesMore").querySelectorAll("input:checked")].map(i => i.value)] : [];
  const reads = [...$("rnReads").querySelectorAll("input:checked")].map(i => i.value);
  const build = $("rnBuildCmd").value.trim(),
        test = $("rnTestCmd").value.trim(), outputs = $("rnOutputs").value.trim();
  const capture_days = $("rnCaptureDays").value.trim();
  const gate = rnGateNow();
  const color = rnColorNow();
  // With the node's group: nothing here restarts a session.
  const tests_in = $("rnDevTest").value || "node";
  const test_change = $("rnTestChange").value || "wait";
  const brief = $("rnBrief").value || "full", reply = $("rnReply").value || "", asks = $("rnAsks").value || "";
  const devbuild = $("rnGateDocker").value || "deny";
  const report = $("rnGateReport").value || "auto";
  const nodeChanged = node !== rnPrefWas.node || nodes.join(",") !== rnPrefWas.nodes || build !== rnPrefWas.build
    || reads.join(",") !== rnPrefWas.reads
    || test !== rnPrefWas.test || outputs !== rnPrefWas.outputs || capture_days !== rnPrefWas.capture_days
    || gateKey(gate) !== rnPrefWas.gate || color !== rnPrefWas.color
    || tests_in !== rnPrefWas.tests_in || test_change !== rnPrefWas.test_change || brief !== rnPrefWas.brief
    || devbuild !== rnPrefWas.devbuild
    || report !== rnPrefWas.report;
  const git_name = $("rnGitName").value.trim(), git_email = $("rnGitEmail").value.trim();
  // Yours, so they travel with the model and the effort rather than with the
  // project's group: the same request, a different store on the server.
  // Only the launch flags are worth interrupting a session for: the model and
  // the effort are read when claude starts, the author is read per commit.
  const launchChanged = model !== rnPrefWas.model || effort !== rnPrefWas.effort;
  const prefChanged = launchChanged || reply !== rnPrefWas.reply || asks !== rnPrefWas.asks
    || git_name !== rnPrefWas.git_name || git_email !== rnPrefWas.git_email;
  const running = liveSessions().has(myClaude(name));
  const fail = m => ($("rnErr").textContent = m, $("rnErrWrap").hidden = false);
  if (!to.trim()) return fail("a new name is needed");
  if (capture_days !== "" && !/^\d{1,3}$/.test(capture_days))
    return fail("captures kept is a number of days, 0 to 365");
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
  const restartNow = !(launchChanged && running)
    ? false
    : confirm(`End the Claude session in ${name} now?\n\n`
        + `OK ends it; press Claude to start it again on the new setting, with `
        + `the conversation resumed. Cancel saves the setting and leaves it `
        + `running.`);
  // Only what actually changed goes to the server. A rename request is
  // refused outright while a terminal is open, so a settings-only save must
  // not make one: it would fail on a project you were sitting in.
  const renaming = to.trim() !== name;
  const needRename = renaming || !!token || !!auth || clear_token;
  $("rnGo").disabled = true; $("rnGo").textContent = "Saving…";
  const stop = m => { $("rnGo").disabled = false; $("rnGo").textContent = "Save";
                      return fail(m); };
  try{
    if (prefChanged || nodeChanged){
      const r = await fetch("/api/prefs", {method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({project: name, model, effort, git_name, git_email,
                              node, nodes, reads, build, test, gate, color,
                              tests_in, test_change, brief, reply, asks, devbuild, report,
                              outputs: outputs.split(",").map(x => x.trim()).filter(Boolean),
                              ...(capture_days !== "" ? {capture_days: +capture_days} : {}),
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
    if (!needRename){
      closeRename();
      if (!prefChanged && !nodeChanged) return;   // nothing changed
      refresh();
      return;
    }
    const r = await postJSON("/api/rename", {name, to, token, auth, clear_token});
    const j = await r.json();
    if (j.error) return stop(j.error);
    closeRename();
    // Named rather than assumed: sanitizing may have changed what was typed,
    // and the operator should see the name that actually exists.
    notify(j.failed?.length
      ? `${name} is now ${j.name}, but ${j.failed.length} thing(s) did not `
        + `move: ${j.failed.join("; ")}`
      : renaming ? `${name} is now ${j.name}` : `${name} saved`,
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
