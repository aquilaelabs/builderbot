// The Docker manager: a project's dev instances on a node, and the container
// editor behind them. Its own classic script beside index.html, per the
// new-surface rule (docs/nodes.md §13): same page, same global scope, one
// file per surface (roadmap R55 step 4).
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs;
// this file only fills slots. Every action is a JOB on the node that owns the
// daemon, so the row reports progress rather than blocking on a request.
//
// dmRowsHtml and dmWireRows stay PAGE-LEVEL names on purpose: the notebook's
// own Docker view (loadNbDocker, still in index.html) draws its rows with
// them, and a classic script shares one global scope, which is what makes
// that work without an export.
//
// Moved out of index.html unchanged. Loaded BEFORE the page's own script, so
// everything here is a declaration and nothing runs at load.

// The one answer, from the poll. `on` absent (an older server, a payload that
// has not landed yet) is not "off": a control the page has no opinion about
// should behave as it always did rather than switch itself off on a hunch.

"use strict";

const dockerWhy = () =>
  state?.docker && state.docker.on === false
    ? (state.docker.why || "no docker daemon is reachable from here") : "";

// The poll's verdict, but only where it is about the node being looked at:
// state.docker is the DEFAULT node's answer, and a picked node answers for
// itself through its own overview (B109).
//
// An answer that does not say which daemon it is about is applied to NONE of
// them. The first cut of this read `state.docker.node || dockerNode`, which
// reads as caution and is the opposite: with the field absent, which it was,
// because nothing set it: the comparison became "this node equals itself"
// and every node's rows were grayed by the default node's silence again, with
// the guard sitting right there looking like it worked. Failing open costs
// nothing: the tab's own overview reports its node's daemon, and that is what
// grays a row whose daemon is genuinely down.
const dmPollSays = () => {
  const about = state?.docker?.node;
  if (dockerNode && about !== dockerNode) return "";
  return dockerWhy();
};

// Whether this list knows what is actually running. One function because the
// rows' ghosting and Remove's confirmation are the same question asked twice,
// and two copies of it would drift.
// `stale` does NOT count: a listing kept from before the node's current job
// is the last thing the daemon said, not a silence, and treating it as one
// drew "the daemon is not answering" on every row through every build. The
// pill says "as last seen" for it instead, and the actions stay live: they
// go through the agent, which is not what is busy.
const dmBlind = () =>
  !!(dockerList?.blind || dockerList?.error || dmPollSays());

// Applied to the DOM after a list draws rather than woven into each renderer,
// four places render one of these controls, and one function that switches
// them off is the only shape that cannot drift between them. Disable only:
// every renderer here redraws from state, so a daemon coming back is picked up
// by the next ordinary draw and nothing has to remember what it switched off.
function gateDocker(root, why){
  // THE CALLER SAYS WHICH DAEMON, always. There used to be a fallback to the
  // poll's answer for a caller that passed nothing, and the poll's answer is
  // about the DEFAULT node, so a project whose own node was fine had its
  // controls switched off because a different machine was down, and a
  // healthy node picked in the manager was gated by the default one's
  // absence, which is the single wrong answer a picker can give (B109). Both
  // callers know which daemon they are about; the fallback existed only to
  // be wrong, so it is gone rather than defaulted.
  if (!why) return;
  (root || document).querySelectorAll(DOCKER_ACTS).forEach(b => {
    b.disabled = true;
    // As `title`, and left for the surface to do what it does with one: the
    // manager tab runs tipify() after this and turns it into a data-tip, the
    // dev row does not and keeps the native tooltip its neighbors use. Which
    // means the reason is worn the same way as every other explanation on
    // whichever surface it lands, rather than in a third style of its own.
    b.title = why;
  });
}

// ---- the docker manager -------------------------------------------------
// What is actually running on the daemon the dev instances use. All of it,
// not only what this dashboard started: a port taken by something else is
// exactly what you open a list like this to find out about, and a listing
// that showed half would be lying by omission.
let dockerList = null;                   // the picked node's last answer
let dockerRev = 0;                       // bumped when it changes, so a pane
                                         // showing the same tab still repaints
// Which node the manager is looking at ("" = the default), and
// the last-known answer per node id: switching back to an offline node shows
// what was seen there instantly, in the ghosted state the blind path already
// renders, instead of a spinner for a machine that will not answer.
let dockerNode = "";
const dockerSeen = {};

// The node the tab is on rides in its `arg`, which is the one part of a tab
// that is saved. `identity()` for a kind that is not `multi` is the kind
// alone, so the arg can change without splitting the tab in two, and a
// reload stops landing on whichever node is the DEFAULT, which is not the one
// anybody picked and was reliably the second entry in the picker.
function dockerTab(){ return tabs.find(t => t.kind === "docker"); }

// What this tab draws from the node list: the picker's rows. The list
// itself moves on every heartbeat (nodes.rev folds the agent's numbers in),
// and a tab keyed on the whole of it repainted for every one while a Nodes
// tab was open anywhere in the layout, though nothing it shows had changed
// (B210's second half). A node arriving, leaving, renamed or changing state
// still repaints, because that is what the picker is made of.
function dmNodesKey(){
  if (nodesList === null) return "?";
  return nodesList.filter(n => n.kind !== "local")
    .map(n => [n.id, n.name, n.kind, n.state].join(",")).join(";");
}

function openDocker(){
  const t = dockerTab();
  if (!dockerNode && t?.arg && t.arg !== "__docker") dockerNode = t.arg;
  openTab({kind: "docker", arg: dockerNode || "__docker", label: "Docker"});
  // Opening is a look: a tab already on screen is read again. Not while an
  // answer is on its way, which is the case the tab's own open hook just
  // made when the list was empty.
  if (!dockerFetching) loadDocker();
}

// ...and remembered when it changes, which is the only moment it can be
// written: the picker is the only thing that moves it deliberately.
function dockerNodeKeep(){
  const t = dockerTab();
  if (!t) return;
  const want = dockerNode || "__docker";
  if (t.arg === want) return;
  t.arg = want;
  saveLayout();
}

let dockerAsk = 0;                       // which ask is newest, so an older
                                         // answer landing late cannot win
let dockerFetching = false;        // an answer is on its way: the tab says so
// ...but only said once it has been slow. A fetch here is one per revision
// while a job runs, which is one per log line, and a word that appeared for
// each of them blinked at the foot of the tab through every build. Under this
// long, nothing is said: an answer that arrives at once needs no announcing.
const DM_SLOW_MS = 600;
let dmSlowTimer = null, dmSlow = false;
async function loadDocker(){
  const asked = dockerNode;
  const ask = ++dockerAsk;
  dockerFetching = true;
  clearTimeout(dmSlowTimer);
  dmSlowTimer = setTimeout(() => {
    if (ask === dockerAsk && dockerFetching){ dmSlow = true; dockerRev++; drawPanes(); }
  }, DM_SLOW_MS);
  let got;
  try{
    got = await (await fetch("/api/docker"
      + (asked ? "?node=" + encodeURIComponent(asked) : ""))).json();
  }catch(e){ got = {error: String(e), containers: []}; }
  // An answer for a node the operator has already picked away from must not
  // repaint the view it no longer belongs to; it lands in that node's cache
  // and nothing else.
  dockerSeen[got.node || asked || ""] = got;
  if (ask === dockerAsk){ dockerFetching = false; dmSlow = false; clearTimeout(dmSlowTimer); }
  if (asked !== dockerNode) return;
  // A newer ask is in flight or has landed: Refresh under a revision reload,
  // or a reload under Refresh. This answer is about an earlier moment, and a
  // daemon that came back between the two would be painted as gone again
  // (B69).
  if (ask !== dockerAsk) return;
  // First answer resolves "" to the default node's real id, so the picker
  // and the cache speak one language.
  if (!dockerNode && got.node) dockerNode = got.node;
  dockerList = got;
  dockerRev++;
  // drawPanes rather than reaching into a pane by index: which pane holds this
  // tab is the layout's business, and toolchains already refreshes this way.
  drawPanes();
}

// Naming a container from a project. The name says WHICH of that project's
// containers this is; what it is built from is settled by the project, which
// is why there is nothing else to fill in here.
let dnFor = null;

// Where a sent container goes: one of the nodes of the project it will
// belong to (the one under Project, its own by default), the primary picked,
// said under the field. A project with no node has nowhere to send, and
// Create is dead until it is given one (R82, R79: a container elsewhere is
// out of reach of the project's sessions). Not the node the manager happens
// to be looking at: this dialog opens from the Artifacts tab too. Filled
// again when the node list lands if this dialog is still the one open.
function dnNodeSay(){
  const project = dnFor;
  if (!project) return;
  const whose = $("dnUnder").value || project;
  const row = state?.projects?.find(p => p.name === whose);
  const set = (row?.prefs?.nodes || []).filter(Boolean);
  const say = $("dnNodeHint"), field = $("dnNodeField");
  if (!set.length){
    field.hidden = false; $("dnNode").innerHTML = ""; $("dnNode").disabled = true;
    say.textContent = whose + " has no node: set one in its settings first, and the container goes there.";
    say.classList.add("bad");
    $("dnGo").disabled = true;
    return;
  }
  fillNodeSelect($("dnNode"), field, set[0],
                 () => { if (dnFor === project && !$("dnmodal").hidden) dnNodeSay(); }, set);
  say.textContent = set.length > 1
    ? `One of ${whose}'s nodes, its primary unless picked; an instance stays where it was made.`
    : `${whose}'s node, ${esc(row?.node_name || "")}: where its sessions can reach it.`;
  say.classList.remove("bad");
  $("dnGo").disabled = false;
}

// `sendAs` is the name the server offers (send_name): the project's own
// while it has none, which is what Send means then, and after that one
// beside it, so pressing Send again makes another container rather than a
// refusal naming the first (the operator, 26 Sep). `have` is how many it
// has already, whose ports a second one must not take.
function openSendToDocker(project, sendAs, have){
  dnFor = project;
  $("dnTitle").textContent = "New container from " + project;
  $("dnName").value = sendAs || project;
  $("dnErrWrap").hidden = true;
  $("dnPreview").hidden = true;
  $("dnGo").disabled = false; $("dnGo").textContent = "Create";
  $("dnHint").textContent = have
    ? `Built from ${project}'s codebase, beside the ${have === 1 ? "one" : have} it already has: give it ports of its own.`
    : `Built from ${project}'s codebase. Its own name makes its own container; another name makes a second one.`;
  $("dnEnvField").hidden = true;
  $("dnEnv").value = "";
  fillUnderSelect($("dnUnder"), project);
  dnNodeSay();
  // The branches the manager already knows about for this project; it lists
  // them per project on the answer the tab is drawn from, so the dialog costs
  // nothing to fill.
  const refs = dockerList?.refs?.[project] || [];
  $("dnRefField").hidden = !refs.length;
  $("dnRef").innerHTML = `<option value="">whatever the project is on</option>`
    + refs.map(b => `<option value="${esc(b)}">${esc(b)}</option>`).join("");
  $("dnmodal").hidden = false;
  // Fetched per open, and only shown when the project actually declares an
  // example: a blank Environment box on a project with nothing to fill in is
  // a question with no answer.
  fetch("/api/devapp", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({project, action:"starter"})})
    .then(r => r.json()).then(j => {
      if (dnFor !== project || !(j.text || "").trim()) return;
      $("dnEnv").value = j.text;
      $("dnEnvHint").textContent =
        "Copied from " + project + "'s .env.example. Saved for this container when you press Create.";
      $("dnEnvField").hidden = false;
    }).catch(() => {});
}

// The compose slug, which is NOT the project-name rule: that one keeps dots,
// and a compose project name may not have them. Mirrors _slug() in devapp.py,
// and a test asserts the two agree on the fixture whose name has a dot in it.
const dockerSlug = (s) => (s || "").toLowerCase()
  .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

// Fill a dialog's node select from the registry: shown only when there is
// an actual choice, because a select with one option is furniture. `prefer`
// is the project's own binding (its settings dialog), else the manager's
// current pick, else the default node.
// `prefer` is the node the caller wants picked: the project's primary, or
// the node the manager is looking at. `allow` narrows the list to the
// project's own node set (R82): a container lives on one of its project's
// nodes and nowhere else, since a session reaches only those (R79), so
// nothing outside the set is offered. With one node to offer the picker
// still shows, disabled, so the dialog says where the container goes.
// `again` is called once the node list lands when it was not here yet, so
// a dialog opened before the first Nodes fetch (the Artifacts tab's Send)
// gets its picker instead of hiding it and sending "".
function fillNodeSelect(sel, wrap, prefer, again, allow){
  // Every node when nothing narrows: a node does everything for the
  // projects bound to it (docs/nodes.md §13).
  const dnodes = (nodesList || []).filter(n =>
    n.kind !== "local" && n.state !== "retired" && (!allow || allow.includes(n.id)));
  // ...and drawn again when they land: loadNodes repaints only a Nodes tab,
  // so a draw here during a node-list reload lost the picker until something
  // else moved dockerRev (B69's nodes.mjs sibling).
  if (nodesList === null) loadNodes().then(() => { dockerRev++; drawPanes(); if (again) again(); });
  const known = dnodes.some(n => n.id === prefer);
  wrap.hidden = allow ? dnodes.length < 1 : dnodes.length < 2;
  sel.disabled = dnodes.length < 2;
  const want = known ? prefer : (dnodes[0]?.id || "");
  // An agent node carries its heartbeat's numbers, and this is the picker
  // the design says they belong beside (docs/nodes.md §9): the choice of
  // where to run a container is made on how busy the machine is.
  sel.innerHTML = dnodes.map(n => {
    const s = n.kind === "agent" && n.live && n.reported?.sample;
    const nums = s ? ` · cpu ${s.cpu_pct}% · ${Math.round(s.mem_used_mb / 1024 * 10) / 10}/${
        Math.round(s.mem_mb / 1024)}GB` : n.kind === "agent" ? " · quiet" : "";
    return `<option value="${esc(n.id)}"${n.id === want ? " selected" : ""}>${
      esc(n.name)}: ${esc(n.state)}${nums}</option>`;
  }).join("");
}

function dnShow(){
  const raw = $("dnName").value, clean = dockerSlug(raw);
  // Only when the name it makes differs from what was typed. A container is
  // called exactly what you called it, so most of the time there is nothing
  // to warn about and the line stays out of the way.
  $("dnPreview").hidden = !raw.trim() || clean === raw.trim();
  $("dnPreview").textContent = clean
    ? `Will be created as ${clean}`
    : "That leaves nothing to name a container after";
}

function closeSendToDocker(){ $("dnmodal").hidden = true; dnFor = null; }

async function dnSubmit(){
  const project = dnFor, name = $("dnName").value.trim();
  const fail = m => ($("dnErr").textContent = m, $("dnErrWrap").hidden = false);
  if (!name) return fail("a name is needed");
  if ($("dnGo").disabled) return;
  $("dnGo").disabled = true; $("dnGo").textContent = "Creating…";
  try{
    const r = await fetch("/api/devapp", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({project, action:"new", instance:name,
                            owner: $("dnUnder").value,
                            node: $("dnNodeField").hidden ? "" : $("dnNode").value,
                            ref: $("dnRefField").hidden ? "" : $("dnRef").value,
                            text: $("dnEnvField").hidden ? "" : $("dnEnv").value})});
    const j = await r.json();
    if (j.error){ $("dnGo").disabled = false; $("dnGo").textContent = "Create";
                  return fail(j.error); }
    closeSendToDocker();
    // ...and build it. The manager lists what exists, so a container that was
    // only registered would not appear there: "send to" has to produce
    // something, or it sends you to a page that does not mention it. The
    // build carries the same confirmations pressing Build there would.
    openDocker();
    await dmAction(project, j.instance, "rebuild");
  }catch(e){ $("dnGo").disabled = false; $("dnGo").textContent = "Create";
             return fail("could not create it: " + e); }
}

// The job, if one is running. It comes with the overview rather than off the
// status snapshot: this page redraws on the devapp revision, which is exactly
// what a build moves, so the two arrive together and cannot disagree.
// The env editor, at module scope because two places open it now: the manager,
// where the controls live, and nothing else; it used to close over the
// artifacts renderer's `project`, which is why it had to move rather than be
// called from there.
async function openDevEnv(project, instance){
  let j;
  try{
    const r = await postJSON("/api/devapp", {project, instance, action: "env-get"});
    j = await r.json();
  }catch(e){ notify("env: " + e, true); return; }
  const m = document.getElementById("devEnvModal");
  m.querySelector("textarea").value = j.text || "";
  // Both halves: whether this is a draft off the example, and what the STORED
  // file is still missing: the second stays true while the box holds an
  // unsaved draft, which is exactly when it matters.
  m.querySelector(".hint").textContent =
    (j.seeded ? "started from .env.example; nothing saved yet. " : "")
    + ((j.missing || []).length
       ? "missing against .env.example: " + j.missing.join(", ")
       : "everything .env.example declares is set");
  m.hidden = false;
  m.querySelector(".primary").onclick = async () => {
    try{
      const r = await fetch("/api/devapp", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({project, instance, action: "env-set",
                              text: m.querySelector("textarea").value})});
      const k = await r.json();
      if (k.error){ notify(k.error, true); return; }
      m.hidden = true;
      notify("env saved");
      dockerList = null; dockerRev++; loadDocker();
    }catch(e){ notify("env: " + e, true); }
  };
}

// The instance's route (docs/nodes.md §7): the URL it is reached at, and
// the picker for how: lan on a published port, or Tailscale Funnel when
// the node has tailscale. public is named as unbuilt rather than hidden, so
// the record's third mode is visible for what it is. Drawn only for an
// instance that publishes something or already has a route set.
// A route picked and not yet applied, per instance: the tab redraws when
// the daemon answers, and a pick a redraw put back could never be applied.
const dmRouteDraft = {};
const devTestMode = name => (state?.projects || []).find(p => p.name === name)?.prefs?.tests_in
                             || "node";

function dmRouteLine(d){
  const r = d.route;
  const draft = dmRouteDraft[`${d.project}|${d.instance}`] || {};
  const mode = draft.mode ?? r?.mode, port = String(draft.port ?? r?.port ?? "");
  const dirty = (draft.mode != null && draft.mode !== r?.mode)
             || (draft.port != null && String(draft.port) !== String(r?.port ?? ""));
  if (!r || (!r.ports?.length && r.mode === "lan" && !r.url)) return "";
  // Whose each published port is, for the picker, when the instance is more
  // than one container (B252): a bare :3000 beside a bare :7680 said nothing.
  const whose = {};
  if ((d.services || []).length > 1)
    for (const c of d.services) for (const e of c.ports || [])
      whose[String(e).split("->")[0]] = c.service || c.name;
  const link = r.url
    ? `<a href="${esc(r.url)}" target="_blank" rel="noreferrer"${r.ready ? "" : ' class="dim"'}>${esc(r.url)}</a>`
    : `<span class="dim">no address</span>`;
  const modes = [["lan", "lan: the node's address"],
                 ["funnel", r.funnel_ok ? "public link (Tailscale Funnel)" : "public link: needs Tailscale on the node"],
                 ["public", "public (not available yet)"]];
  return `<div class="sub dmroute">${link}${r.why ? ` <span class="dim">· ${esc(r.why)}</span>` : ""}
    <select data-route="mode" data-was="${esc(r.mode)}" aria-label="route" title="how this instance is reached">${
      modes.map(([v, l]) => `<option value="${v}"${v === mode ? " selected" : ""}${
        v === "public" || (v === "funnel" && !r.funnel_ok) ? " disabled" : ""}>${esc(l)}</option>`).join("")}</select>${
    r.ports?.length > 1 ? `<select data-route="port" data-was="${esc(String(r.port))}" aria-label="port" title="which published port">${
      r.ports.map(p => `<option value="${p}"${String(p) === port ? " selected" : ""}>:${p}${
        whose[p] ? ` ${esc(whose[p])}` : ""}</option>`).join("")}</select>` : ""}
    <button type="button" data-routeapply${dirty ? "" : " disabled"} title="save the route">Apply</button></div>`;
}

// Whose Rebuild it is: a line of the row's own text column, beside the route,
// rather than a control in its action bar. The bar was wrong for it twice: its
// sizing is written for buttons (`.actbar input` hands an input a 12em basis,
// which a 15px checkbox spends on nothing), so the label wrapped to three
// words on three lines; and a bar has nothing safe after `.danger`, which a
// checkbox sitting under Remove broke. The long half of the explanation rides
// the `?` rather than a native title, because a title cannot be tapped and
// this tab is read on a phone.
// Which branch this instance builds from. A project's tree is SHARED: every
// session and every person on it sees one checkout, so "build the other
// branch" cannot mean switching it: the Git view refuses that outright while
// somebody's session stands in the directory, and rightly. Pinned here, the
// build comes from a worktree of its own and the project's tree is not
// touched at all.
//
// Staged and applied like the route above it, because it is a setting.
const dmRefDraft = {};

function dmRefLine(d){
  if (d.source === "file" || !mayDocker()) return "";
  const refs = dockerList?.refs?.[d.project] || [];
  if (!refs.length) return "";
  const key = `${d.project}|${d.instance}`;
  const saved = d.ref || "";
  const pick = dmRefDraft[key] ?? saved;
  // The `?` rides the LABEL (docs/design-language.md, Controls), not the end
  // of the row: a row of controls wraps on a phone, and an icon last wrapped
  // onto a line of its own, where it read as a stray mark belonging to
  // nothing.
  return `<div class="sub dmref"><label for="${esc("dmr-" + key)}">Build from${
      helpIcon("The next build uses that branch. The project's checkout, env and data "
        + "stay as they are.")}</label>
    <select id="${esc("dmr-" + key)}" data-dmref="${esc(key)}" aria-label="which branch to build">
      <option value=""${saved ? "" : " selected"}>whatever the project is on</option>${
      refs.map(b => `<option value="${esc(b)}"${b === pick ? " selected" : ""}>${
        esc(b)}</option>`).join("")}</select>
    <button type="button" data-dmrefapply="${esc(key)}"${
      pick === saved ? " disabled" : ""} title="build this container from that branch from now on"
      >Apply</button></div>`;
}

function dmGrantLine(d, other = false){
  // What a Claude session may do with it: the setting of the PROJECT it
  // belongs to (Claude may: Run its container, in that project's settings),
  // said on the row with the words linking there. Nothing for a row that
  // belongs to no project: its group says no session sees it. `other` is a
  // container BuilderBot did not start, which is started and stopped rather
  // than rebuilt.
  if (!d.owner || !mayDocker()) return "";
  const mode = devClaudeMode(d.owner);
  const own = !other && d.owner === d.project && d.source !== "file";
  const says = other
    ? {auto: "may start, stop and restart it", ask: "asks you before starting, stopping or restarting it",
       deny: "may read its log, and not start or stop it"}
    : own
    ? {auto: "may rebuild it, change its env and create it",
       ask: "asks you before rebuilding it, changing its env or creating it", deny: "may not rebuild it"}
    : {auto: "may rebuild it and change its env", ask: "asks you before rebuilding it or changing its env",
       deny: "may not rebuild it"};
  return `<div class="sub dmgrant dmclaudesays">${own ? "Claude" : `${esc(d.owner)}'s Claude`} ${
    says[mode] || says.deny} · <a href="#" data-dmtestgo="${esc(d.owner)}"
      title="the project's settings, where Claude may: Run its container is set">change</a></div>`;
}

// Which project a row belongs to: its group on this tab, the notebook that
// lists it, and whose Claude sessions may see it and work on it (the
// operator, 24 Sep). Staged and applied like the branch above, because it
// is a setting. Keyed `inst:project|instance` or `ctr:name`.
const dmOwnDraft = {};

function dmOwnerLine(r, key){
  if (!mayDocker()) return "";
  const saved = r.owner || "";
  const pick = dmOwnDraft[key] ?? saved;
  const names = (state?.projects || []).map(p => p.name);
  // A project since deleted is still what the row says until it is changed.
  if (saved && !names.includes(saved)) names.push(saved);
  const shown = n => n === saved && r.owner_gone ? `${n} (deleted)` : n;
  names.sort((a, b) => a.localeCompare(b, undefined, {sensitivity: "base"}));
  const id = "dmo-" + key;
  return `<div class="sub dmowner"><label for="${esc(id)}">Project${
      helpIcon("Its project's Claude sessions can see it and, as that project's "
        + "Run its container setting allows, work on it. No project keeps it "
        + "from every session.")}</label>
    <select id="${esc(id)}" data-dmown="${esc(key)}" aria-label="which project it belongs to">
      <option value=""${pick ? "" : " selected"}>no project</option>${
      names.map(n => `<option value="${esc(n)}"${n === pick ? " selected" : ""}>${
        esc(shown(n))}</option>`).join("")}</select>
    <button type="button" data-dmownapply="${esc(key)}"${
      pick === saved ? " disabled" : ""} title="put it under that project">Apply</button></div>`;
}

// Which project a project's own instance is built from, and Move to put it
// under another (the operator, 8 Oct: MediaReducer-Dev's to MediaReducer).
// Its containers, env and data stay as they are; a written container has no
// project behind it and moves with the Project line above.
const dmMoveDraft = {};
function dmMoveLine(d){
  if (!mayDocker() || d.source === "file") return "";
  const key = `${d.project}|${d.instance}`, pick = dmMoveDraft[key] ?? d.project;
  const names = (state?.projects || []).map(p => p.name)
    .sort((a, b) => a.localeCompare(b, undefined, {sensitivity: "base"}));
  // Built from a project since deleted: it is still that one's until moved.
  const gone = !names.includes(d.project);
  if (gone) names.unshift(d.project);
  const id = "dmm-" + key;
  return `<div class="sub dmowner"><label for="${esc(id)}">Built from${
      helpIcon("The project whose compose file and tree it is built from. Move puts it "
        + "under another project, keeping its name, env and data; it then builds "
        + "from that project's tree.")}</label>
    <select id="${esc(id)}" data-dmmove="${esc(key)}" aria-label="the project it is built from">${
      names.map(n => `<option value="${esc(n)}"${n === pick ? " selected" : ""}>${
        esc(gone && n === d.project ? `${n} (deleted)` : n)}</option>`).join("")}</select>
    <button type="button" data-dmmoveapply="${esc(key)}"${
      pick === d.project ? " disabled" : ""} title="move it under that project">Move</button></div>`;
}

function dmTestLine(d){
  // Where a project's tests run is the PROJECT's setting, and it now lives
  // with its node, its build command and its test command, in the settings
  // dialog (R68 step 6). It was here because it is about this container,
  // which is a weak reason to put a project setting on a machine surface:
  // somebody setting up a project had to visit the Docker tab to finish.
  // The row still says what it is set to, because this is where a person
  // wonders about it, and the words are a link to where it is changed.
  if (d.source === "file") return "";
  const mode = devTestMode(d.project);
  return `<div class="sub dmgrant dmtestsays">Tests run ${
    mode === "only" ? "only in this container, never on the node"
    : mode === "up" ? "in this container when it is up, else on the node"
    : "on the node, never in this container"}${
    ` · <a href="#" data-dmtestgo="${esc(d.project)}"
      title="the project's settings, where its node and its test command are">change</a>`}</div>`;
}

function dockerJob(){
  const j = dockerList?.job;
  // While it runs, and while it has something to say about how it ended. The
  // running-only rule meant a build that failed, or one stopped on purpose,
  // which ends a job with no other trace: vanished the instant it finished,
  // leaving the row showing whatever state it happened to be in. The server
  // stops sending it when the next job starts, which is when it stops being
  // the answer to "what just happened here".
  return j && (j.running || j.error) ? j : null;
}

// What the artifact row's buttons used to do, moved here with them. The
// confirmations come with it: taking something down and handing a compose
// file more than its own directory are both decisions, and moving a button
// is not a reason to stop asking.
async function dmAction(project, instance, act, btn){
  if (act === "env"){ openDevEnv(project, instance); return; }

  if (act === "edit"){ openEditContainer(project); return; }
  // Abort asks nothing: the confirmation for a destructive verb is worth its
  // interruption, and stopping a build you are watching is not destructive:
  // what is already built is kept, and pressing it again is the only way to
  // undo an accidental press, which costs a rebuild rather than data.
  if (act === "abort"){
    if (btn) btn.disabled = true;
    try{
      await postJSON("/api/devapp", {project, instance, action: "abort"});
    }
    catch(e){ notify("could not stop it: " + e, true); }
    dockerRev++; drawPanes(); loadDocker();
    return;
  }
  if (act === "down" && !confirm(`Take ${project}/${instance} down?`)) return;
  if (act === "remove" && !confirm(
      `Remove ${project}/${instance}?\n\n`
      // Which of the two halves is actually going to happen. A row whose
      // daemon is not answering loses the down, and somebody removing one
      // should be told that before they press it rather than read it
      // afterwards.
      + (dmBlind()
          ? `Docker is not answering, so it is not taken down; only the row goes. `
          : `It is taken down first. `)
      + `Its env file and data stay for a remake.`)) return;
  let ack = "";
  if (act === "up" || act === "rebuild"){
    // The full state for this one instance, asked now rather than computed
    // for every instance on every paint: risks and problems cost a compose
    // config parse each, and the manager lists them all.
    let st;
    try{
      const r = await postJSON("/api/devapp", {project, instance, action:"state"});
      st = (await r.json()).state || {};
    }catch(e){ notify("could not read its state: " + e, true); return; }
    if ((st.problems || []).length){
      notify(`${project}/${instance} will not work as written: `
             + st.problems.join("; "), true);
      return;
    }
    // A port something else holds: here, where Up is, that is a start that
    // would fail, and the way out is this instance's own env. (The Artifacts
    // view says the same fact as a note, since its Send opens that env.)
    if (act === "up" && (st.port_clash || []).length){
      notify(`port ${st.port_clash.join(", ")} ${st.port_clash.length === 1 ? "is" : "are"} `
             + `published already on this node: set another in this instance's env (Env), then Up`, true);
      return;
    }
    if ((st.missing_env || []).length && act === "up"){
      notify(`the env is missing ${st.missing_env.join(", ")}: press Env`, true);
      return;
    }
    if (act === "rebuild" && !confirm(
        (st.built_rev ? `Rebuild ${project}/${instance}?\n\nBuilds the image, then down and up. `
                      : `Build ${project}/${instance}?\n\nBuilds the first image and brings it up. `)
        + "New env settings stop it before up; the Env editor keeps your old values in comments.")) return;
    if (!st.risks_ack){
      if (!confirm("This compose file asks for more than its own directory:"
          + "\n\n" + (st.risks || []).map(x => "\u2022 " + x).join("\n")
          + "\n\nStart it anyway?")) return;
      ack = st.risks_digest || "";
    }
  }
  if (btn) btn.disabled = true;
  try{
    const r = await postJSON("/api/devapp", {project, instance, action:act, ack});
    const j = await r.json();
    if (j.error) notify(j.error, true);
    // What was done instead of what was asked: a remove whose daemon could
    // not be reached took the record and nothing else. Said, because the row
    // vanishing looks identical either way.
    else if (j.note) notify(j.note);
  }catch(e){ notify(`${act} failed: ` + e, true); }
  dockerList = null; dockerRev++; loadDocker();
}

// Where a container's published port actually answers.
//
// NOT location.hostname, which is the machine serving this page. The daemon
// runs on the sandbox VM: a different machine, which is the entire point of
// the arrangement, and a container publishing 8989 publishes it there. Using
// the page's own host pointed every port label and every Open link at the
// Unraid box, where either nothing answers or, worse, something else does.
//
// Taken from the address the manager is already told about, with the scheme,
// the account and any port stripped: ssh://bb@10.0.0.9 is the machine 10.0.0.9.
// Falls back to this page's host, which is right for the case where there is
// no daemon and therefore no container to open.
function daemonHost(){
  const w = (state?.docker?.where || "").trim();
  const h = w.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")
             .replace(/^[^@/]*@/, "")
             .replace(/[:/].*$/, "");
  return h || location.hostname;
}

// The wiring itself, fetched on the first open. It arrives after the fold has
// already animated to the height of "reading…", so the panel is grown a second
// time when the real lines land: measured either side of the swap, which is
// what keeps the rows below from jumping.
async function loadWire(d){
  d.dataset.done = "1";
  const [project, instance] = d.closest("[data-inst]").dataset.inst.split("|");
  const box = d.querySelector(".wire");
  let html;
  try{
    const r = await postJSON("/api/devapp", {project, instance, action:"state"});
    const st = (await r.json()).state || {};
    const ports = st.ports || [], mounts = st.mounts || [];
    const portLine = p => {
      const at = `${daemonHost()}:${p.published || ""}`;
      // A link only where there is something to open: a port with no
      // published side is picked at start and has no address yet, and a
      // link to a udp port is a link to nothing.
      const body = p.published && /tcp/i.test(p.proto || "tcp")
        ? `<a href="http://${esc(at)}/" target="_blank" rel="noreferrer">${esc(at)}</a>`
        : esc(p.published ? at : "picked at start");
      return `<div class="dim li wport"><span class="wt">${esc(p.target)}:${
        esc(p.proto)}</span> <span class="wa">←</span> ${body}</div>`;
    };
    const mountLine = m => `<div class="dim li wmount"><span class="wt">${
      esc(m.target)}</span> <span class="wa">${m.ro ? "←" : "↔"}</span> ${
      esc(m.source)}</div>`;
    // Which container each line is, when the compose has more than one: a
    // stack's ports in one list could not be told apart (B252, the operator,
    // 24 Sep). A group per service, headed by its name, in the same columns.
    const svcs = [...new Set([...ports, ...mounts].map(x => x.service || ""))].sort();
    const lines = svcs.length > 1
      ? svcs.map(sv => `<div class="wgrp"><div class="lbl wsvc">${esc(sv)}</div>${
          ports.filter(p => (p.service || "") === sv).map(portLine).join("")}${
          mounts.filter(m => (m.service || "") === sv).map(mountLine).join("")}</div>`).join("")
      : ports.map(portLine).join("") + mounts.map(mountLine).join("");
    html = lines || `<div class="dim li">it publishes nothing and mounts nothing</div>`;
  }catch(e){ html = `<div class="dim li bad">could not read it: ${esc(String(e))}</div>`; }
  if (!d.isConnected){
    // The manager repainted under it, because every step of a job does that now,
    // and the fold the operator opened is a fresh, closed one with nothing in
    // it. Carry the answer over rather than drop it: the same instance's new
    // fold gets the lines and stays open, so a build in progress does not
    // snap the wiring shut every half second.
    const inst = d.closest("[data-inst]")?.dataset.inst || `${project}|${instance}`;
    const nd = document.querySelector(
      `.dmtab .row[data-inst="${CSS.escape(inst)}"] details.sect`);
    if (!nd || nd.dataset.done) return;
    nd.dataset.done = "1";
    nd.querySelector(".wire").innerHTML = html;
    if (d.open) nd.open = true;
    return;
  }
  const before = d.offsetHeight;
  box.innerHTML = html;
  const after = d.offsetHeight;
  if (d.open && before !== after && !noMotion()) foldHeight(d, before, after, () => {});
}

// A starting point rather than an empty box. Somebody opening this is about
let cEditing = null;              // the container being edited, or null for new

async function openEditContainer(name){
  cEditing = name;
  $("cTitle").textContent = "Edit " + name;
  $("cName").value = name;
  $("cName").disabled = true;
  $("cNameHint").textContent =
    "The name cannot change: remove it and create it again under another.";
  $("cNodeField").hidden = true;   // where it runs is not an edit either
  $("cUnderField").hidden = true;  // its project is changed on its row
  $("cYml").value = $("cEnv").value = "";
  $("cErrWrap").hidden = true;
  $("cGo").disabled = false; $("cGo").textContent = "Save";
  cSeg("yml");
  $("cmodal").hidden = false;
  try{
    const r = await postJSON("/api/container", {action:"read", name});
    const j = await r.json();
    if (cEditing !== name) return;          // reopened on another one meanwhile
    $("cYml").value = j.compose || "";
    $("cEnv").value = j.env || "";
  }catch(e){ $("cErr").textContent = "could not read it: " + e;
             $("cErrWrap").hidden = false; }
}

// Which project a new container belongs to: every project this account
// sees, no project first.
function fillUnderSelect(sel, picked){
  const names = (state?.projects || []).map(p => p.name).sort((a, b) => a.localeCompare(b));
  sel.innerHTML = `<option value="">no project</option>` + names.map(n =>
    `<option value="${esc(n)}"${n === picked ? " selected" : ""}>${esc(n)}</option>`).join("");
}

// The node follows the project picked: a container of a project belongs on
// the node that project's work runs on, and a person picking the project is
// not also asked to know which machine that is. A project with no node
// leaves the pick where it was.
function cUnderPicked(){
  const whose = $("cUnder").value;
  const row = state?.projects?.find(p => p.name === whose);
  const set = whose ? (row?.prefs?.nodes || []).filter(Boolean) : null;
  const hint = $("cNodeHint");
  if (whose && !set.length){
    $("cNodeField").hidden = false; $("cNode").innerHTML = ""; $("cNode").disabled = true;
    hint.hidden = false; hint.classList.add("bad");
    hint.textContent = whose + " has no node: set one in its settings first, and the container goes there.";
    $("cGo").disabled = true;
    return;
  }
  // No project: any node, the one the manager is looking at first. A
  // project: its nodes only, its primary first (R82).
  fillNodeSelect($("cNode"), $("cNodeField"), set ? set[0] : dockerNode, null, set);
  hint.hidden = !set; hint.classList.remove("bad");
  if (set) hint.textContent = set.length > 1 ? `One of ${whose}'s nodes.` : `${whose}'s node, where its sessions can reach it.`;
  $("cGo").disabled = false;
}

function openNewContainer(){
  cEditing = null;
  $("cName").disabled = false;
  $("cName").value = "";
  fillUnderSelect($("cUnder"), "");
  $("cUnderField").hidden = false;
  // Left EMPTY, both of them. The shape each wants is on the field as a
  // placeholder, which shows the same thing and cannot be submitted: seeded
  // as values, an example compose for a radarr nobody asked for was one
  // unread click from being created under whatever name was typed.
  $("cYml").value = $("cEnv").value = "";
  // Created on the node the manager is looking at, unless picked otherwise,
  // or a project is: cUnderPicked moves it to that project's node.
  const fillC = () => fillNodeSelect($("cNode"), $("cNodeField"), dockerNode,
    () => { if (cEditing === null && !$("cmodal").hidden) cUnderPicked(); });
  fillC();
  $("cNodeHint").hidden = true;
  $("cErrWrap").hidden = true;
  $("cGo").disabled = false; $("cGo").textContent = "Create";
  for (const id of ["cImage", "cPorts", "cVols", "cEnvLines"]) $(id).value = "";
  $("cRestart").value = "unless-stopped";
  cYmlTouched = false;
  // The form first: an image and a port is what most of these are, and the
  // compose file it writes is one tab away for everything else.
  cSeg("form");
  $("cNameHint").textContent =
    "A name no other container has.";
  $("cmodal").hidden = false;
}

let cTab = "yml";                 // which pane the segment is showing

function cSeg(which){
  cTab = which;
  $("cTabForm").classList.toggle("on", which === "form");
  $("cTabYml").classList.toggle("on", which === "yml");
  $("cTabEnv").classList.toggle("on", which === "env");
  $("cFormField").hidden = which !== "form";
  $("cYmlField").hidden = which !== "yml";
  $("cEnvField").hidden = which !== "env";
}

// Once the compose file has been edited by hand the form stops writing it:
// a generator that overwrites what somebody typed is a generator that eats
// work. Reset on every open.
let cYmlTouched = false;

// The form's answer, as the compose file it stands for. Written here rather
// than on the server because what is about to be created should be readable
// before it is: the Compose tab shows exactly the text that will be saved,
// and the server still checks it with compose itself before writing it.
function cFormYaml(){
  const lines = l => l.split("\n").map(x => x.trim()).filter(Boolean);
  const image = $("cImage").value.trim();
  const ports = lines($("cPorts").value), vols = lines($("cVols").value);
  const env = lines($("cEnvLines").value), restart = $("cRestart").value;
  if (!image) return "";
  // Quoted, every one of them: a port reads as a base-60 number in YAML
  // ("7878:7878" is a sexagesimal literal to a YAML 1.1 parser), and a value
  // with a colon or a space in it needs quoting anyway. Double quotes with
  // the two escapes that matter inside them.
  const q = v => `"${String(v).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
  const block = (key, xs) => xs.length
    ? `\n    ${key}:\n` + xs.map(x => `      - ${q(x)}`).join("\n") : "";
  return `services:\n  app:\n    image: ${q(image)}\n    restart: ${restart}`
    + block("ports", ports) + block("volumes", vols) + block("environment", env) + "\n";
}

function cFormWrote(){
  if (cYmlTouched) return;
  $("cYml").value = cFormYaml();
}

// Switching between them moves the way the New project dialog's source picker
// does: the incoming pane slides in from its own tab's side (Compose is the
// left tab, Environment the right), same 220ms ease, same reduced-motion gate.
// One vocabulary for every two-tab switch on the page; see pSlide, which is
// this in the other dialog. Not called from cSeg: an open draws its first pane
// rather than switching to it, and sliding on arrival would animate a dialog
// that is already animating itself in.
function cSlide(which){
  if (noMotion()) return;
  $({form: "cFormField", yml: "cYmlField", env: "cEnvField"}[which]).animate(
    [{transform: `translateX(${
        {form: -18, yml: 0, env: 18}[which] >= 0 ? "18px" : "-18px"})`, opacity: 0},
     {transform: "none", opacity: 1}],
    {duration: 220, easing: "ease"});
}

const cSwitch = w => { if (cTab === w) return; cSeg(w); cSlide(w); };

async function cSubmit(){
  const fail = m => ($("cErr").textContent = m, $("cErrWrap").hidden = false);
  const editing = cEditing, verb = editing ? "Save" : "Create";
  if (!$("cName").value.trim()) return fail("a name is needed");
  $("cGo").disabled = true; $("cGo").textContent = editing ? "Saving…" : "Creating…";
  try{
    const r = await fetch("/api/container", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({action: editing ? "save" : "create",
                            name: editing || $("cName").value,
                            node: editing ? "" : ($("cNodeField").hidden
                              ? (dockerNode || "") : $("cNode").value),
                            owner: editing ? "" : $("cUnder").value,
                            compose: $("cYml").value, env: $("cEnv").value})});
    const j = await r.json();
    if (j.error){
      $("cGo").disabled = false; $("cGo").textContent = verb;
      // Compose's own complaint, which names the line: shown on the tab the
      // text is on, since that is where it has to be fixed.
      cSeg("yml");
      return fail(j.error);
    }
    $("cmodal").hidden = true;
    if (!editing){
      notify(`${j.name} is in the manager: press Build to bring it up`);
      dockerList = null; dockerRev++; loadDocker();
      return;
    }
    // Saved. If it has been built, the change is on disk and not in the
    // running container: a state worth resolving now rather than leaving for
    // the row to hint at, because the gap between "I edited it" and "it is
    // running what I edited" is where the confusion lives. Asked rather than
    // done: a rebuild takes it down and brings it up, which is not something
    // to start on somebody's behalf because they pressed Save.
    const row = (dockerList?.instances || []).find(
      d => d.project === editing && d.instance === "main");
    dockerList = null; dockerRev++; loadDocker();
    if (row?.built_rev && confirm(
          `${editing} is saved. Rebuild it now so the change takes effect?\n\n`
          + `Cancel keeps the change on disk for a later Rebuild.`)){
      dmAction(editing, "main", "rebuild", null);
      return;
    }
    notify(`${editing} saved: ${j.note || "rebuild it to bring the change up"}`);
  }catch(e){ $("cGo").disabled = false; $("cGo").textContent = verb;
             return fail("could not create it: " + e); }
}

// How a job ENDED, in one line: the LAST non-empty line of its error, not the
// first.
//
// These errors are "<what failed>:\n<the tool's own output>", kept from the
// END (devapp's `("up failed:\n" + out)[-500:]`), so the first line is the
// LABEL and the row showed "up failed:" with docker's actual reason dropped.
// That is the same mistake the agent made printing a dead toolchain's first
// line: ".NET said: Process terminated." and nothing of the sentence after
// it that named the missing library. Where an error is one line, the first
// and the last are the same line and nothing changes.
function jobWhy(err){
  const lines = String(err || "").split("\n").map(l => l.trim()).filter(Boolean);
  return lines.length ? lines[lines.length - 1] : "";
}

// What a build was made FROM, in the row's own words.
//
// The ref here is the one stamped AT BUILD TIME, never the Ref line's value.
// That line is the setting for the next build, and repointing an instance does
// not rebuild it, so reading the setting to describe what is already built
// says "built from rack-drift 244e38d" about a branch that may never have been
// built here at all. The commit is the truth; the branch is the setting, and
// the moment the two disagree is the moment this line is worth reading.
function dmBuilt(d){
  return `built from ${d.built_ref ? esc(d.built_ref) + " " : ""}${
    esc(d.built_rev)}`;
}

// What one dev instance is doing, in a line: the action bar's status.
function dmState(d, job, mine, busy, blind){
  // A job in flight on this row is known whatever the listing says: its
  // phase comes from the job, not from the daemon.
  if (busy) return esc(job.step || "working") + '<span class="dots"></span>';
  // Nothing was asked, so nothing is claimed. What it was built from is still
  // true (that is a record on this side) and it is the one fact worth
  // carrying into a listing nobody can act on.
  if (blind)
    return d.built_rev
      ? `${dmBuilt(d)}: the daemon is not answering, so whether it is up is
         unknown`
      : "never built: the daemon is not answering";
  // How a job ENDED, which this row never said. A build that failed or was
  // stopped left the row showing the state it happened to be in, so the only
  // account of what went wrong was in the tail below it, and an abort, which
  // ends a job on purpose, said nothing at all.
  if (mine && job.error) return esc(jobWhy(job.error));
  if (d.running) return `running · ${d.containers} container(s)`;
  if (d.exists) return "stopped: its containers are still there";
  if (d.built_rev) return `${dmBuilt(d)}, not running`;
  return "never built";
}

// One instance row: the same markup wherever the row is drawn, the Docker
// tab and a project's notebook (its Docker view). `job` is the compose job
// the answer carried and `blind` whether the daemon answered at all.
async function dmLogs(name, node = dockerNode){
  const modal = $("dlmodal"), body = $("dlBody");
  if (!modal || !body) return;
  $("dlTitle").textContent = `Log: ${name}`;
  body.innerHTML = `<div class="field"><div class="loading">reading…</div></div>`;
  modal.hidden = false;
  try{
    // The node the list came from: a project's notebook lists its own
    // node's containers, which is not the tab's pick.
    const r = await postJSON("/api/dockerctl", {action: "logs", container: name, node});
    const j = await r.json();
    body.innerHTML = `<div class="field">${j.error
      ? `<div class="hint bad">${esc(j.error)}</div>`
      : j.text && j.text.trim()
        ? `<pre class="dmlog dllog">${esc(j.text)}</pre>`
        : `<div class="hint">It has printed nothing.</div>`}</div>
      <div class="foot"><span class="sp"></span>
        <button type="button" id="dlAgain">Read again</button>
        <button type="button" id="dlClose">Close</button></div>`;
    // At the end, which is where a log's reason is: the top of a tail is the
    // middle of whatever happened before it.
    const pre = body.querySelector("pre");
    if (pre) pre.scrollTop = pre.scrollHeight;
    body.querySelector("#dlClose").onclick = () => { modal.hidden = true; };
    body.querySelector("#dlAgain").onclick = () => dmLogs(name);
  }catch(e){
    body.innerHTML = `<div class="field"><div class="hint bad">${esc(String(e))}</div></div>
      <div class="foot"><span class="sp"></span><button type="button" id="dlClose">Close</button></div>`;
    body.querySelector("#dlClose").onclick = () => { modal.hidden = true; };
  }
}

function dmRowsHtml(ins, job, blind){
  return ins.map(d => {
    // Explicitly running: dockerJob() keeps a finished job around now so the
    // row can say how it ended, and "busy" must not follow it there: a
    // stopped build would otherwise keep its Abort and its ghosted buttons
    // forever.
    const mine = job && job.project === d.project && job.instance === d.instance;
    const busy = !!(mine && job.running);
    // A one-shot that ran and exited 0 (a seed, a migration) has done its
    // job: it is neither up nor down, and counting it as down said an
    // instance was partly up when nothing was wrong (B147).
    const finished = c => c.state === "exited" && /^Exited \(0\)/.test(c.status || "");
    const live = (d.services || []).filter(c => !finished(c));
    return `
    <div class="row stack2${blind ? " off" : ""}" data-inst="${
      esc(d.project)}|${esc(d.instance)}">
      <div class="grow">
        <div class="dmid">
        <div class="name">${esc(d.name)}
          <span class="dim dmpill ${!blind && d.running ? "ok" : ""}">(${
            blind ? "state unknown"
            : d.running && live.some(c => c.state !== "running")
              ? `partly up: ${live.filter(c => c.state === "running").length} of ${live.length}`
            : d.running ? "running" : d.exists ? "stopped" : "down"}${
            dockerList?.stale && !blind ? ", as last seen" : ""})</span></div>
        <div class="sub">${d.source === "file"
          ? `written here: this dashboard holds its compose file`
          : `from ${esc(d.project)}'s compose file${
              d.instance && d.instance !== "main" ? `, as ${esc(d.instance)}` : ""}`}</div>
        </div>
        <details class="dmdet"${
          // Remembered on a phone, where it is a fold. On a desktop its summary
          // is not drawn, so a shut one could never be opened again: always open.
          isPhone() ? sectAttr(`docker:det:${d.project}|${d.instance}`)
                    : ` data-sect="${esc(`docker:det:${d.project}|${d.instance}`)}" open`}>
          <summary class="dmsum"><span class="t">Details</span><span class="sst">${
            [d.ports.length ? `${d.ports.length} port${d.ports.length === 1 ? "" : "s"}` : "",
             (d.services || []).length > 1 ? `${d.services.length} services` : ""]
              .filter(Boolean).join(" · ") || "settings"}</span></summary>
        ${d.ports.length ? `<div class="sub dmports">${
          // Whose each port is, when the instance is more than one
          // container (B252): the list below then says only how each is.
          (d.services || []).length > 1
            ? d.services.filter(c => (c.ports || []).length).map(c =>
                `${esc(c.service || c.name)}: ${c.ports.map(esc).join(", ")}`).join(" · ")
            : d.ports.map(esc).join(" · ")}</div>` : ""}
        ${(d.services || []).length > 1 ? `<div class="sub dmsvcs">${d.services.map(c =>
          `<span class="dmsvc ${c.state === "running" ? "ok" : finished(c) ? "" : "dim"}" title="${esc(c.image || "")}">${
            esc(c.service || c.name)}: ${finished(c) ? `finished (${esc(c.status)})` : esc(c.status || c.state)}</span>`).join("<br>")}</div>` : ""}
        ${dmRouteLine(d)}
        ${d.astray ? `<div class="sub bad">on this node, but ${esc(d.owner || d.project)} works on ${
          esc(d.astray)}: its sessions cannot reach it here. Remove it and Send to Docker again to build it there.</div>` : ""}
        <div class="dmsettings">${dmOwnerLine(d, `inst:${d.project}|${d.instance}`)}${dmMoveLine(d)}${
          dmRefLine(d)}${dmGrantLine(d)}${dmTestLine(d)}${d.exists
          ? dmBootLine(d.name, !!d.boot) : ""}</div>
        ${d.await_env ? `<div class="sub warn">built: fill in the env, then Up</div>` : ""}
        </details>
      </div>
      <div class="actbar dmacts">
        <span class="state${!blind && d.running ? " ok" : ""}">${dmState(d, job, mine, busy, blind)}</span>
        ${!mayDocker() ? "" : `<button type="button" data-dm="up" ${
          d.running || busy || (d.missing_env || []).length ? "disabled" : ""}
          title="${(d.missing_env || []).length
            ? "the env is missing " + esc(d.missing_env.join(", "))
            : !d.built_rev
              ? "Start it: docker compose up -d, which builds the image first, as compose does"
              : "Start it: docker compose up -d"}">Up</button>
        <button type="button" data-dm="down" ${!d.exists || busy ? "disabled" : ""}
          title="Stop it and remove its containers: docker compose down">Down</button>
        ${d.source === "file"
          ? `<button type="button" data-dm="edit"
               title="edit this container's compose file and env">Edit</button>`
          : `<button type="button" data-dm="env"
               title="this container's env file">Env</button>`}
        `}
        ${busy ? `<button type="button" data-dm="abort" ${
            job.aborting ? "disabled" : ""}
            title="stop this build; what is already built is kept"
            >${job.aborting ? "Stopping…" : "Abort"}</button>` : ""}
        <button type="button" data-dm="rebuild" ${
          // A button that refuses is not information. This slept whenever the
          // build matched the code, which is defensible and was read as
          // broken: the operator pinned an instance to a branch, pressed
          // Apply, and had nothing to press. What "the code has moved" is
          // worth is a SENTENCE, which the state line above and this title
          // both carry, and a rebuild when nothing moved is a cached build
          // and a restart, behind a confirm that says so.
          busy ? "disabled" : ""}
          title="${!d.built_rev
            ? "build the first image, then bring it up"
            : d.changed
              ? "build from " + esc(d.ref || d.project) + "'s codebase, then down and up"
              : (mine && job.error)
                ? "run it again: the last attempt did not finish"
                : "the last build is current; this builds it again anyway"}">${
          d.built_rev ? "Rebuild" : "Build"}</button>
        ${!mayDocker() ? "" : `<button type="button" class="danger" data-dm="remove" ${
            busy ? "disabled" : ""}
            title="take it down and drop it from this list; its env and data stay for a remake">Remove</button>`}
      </div>
      ${docSection("docker", `wire:${d.project}|${d.instance}`,
                   "Ports and mounts", "",
                   `<div class="wire">reading…</div>`, {open: false})}
    </div>`;
  }).join("");
}

// ...and the handlers those rows need, wired onto whichever element holds
// them. `list` is the answer the rows were drawn from, for the saved values
// a pick is compared against.
function dmWireRows(el, list = dockerList){
  wireSections(el);
  el.querySelectorAll("details.sect").forEach(d => {
    const sum = d.querySelector(":scope > summary");
    if (!sum) return;
    sum.onclick = (e) => {
      e.preventDefault();
      const willOpen = !d.open;
      slideDetails(d, willOpen);
      if (willOpen && !d.dataset.done) loadWire(d);
    };
  });
  el.querySelectorAll("[data-dm]").forEach(btn => btn.onclick = () => {
    const [project, instance] = btn.closest("[data-inst]").dataset.inst.split("|");
    dmAction(project, instance, btn.dataset.dm, btn);
  });
  // Whose Rebuild it is. Written at once, like the row's other controls, and
  // the answer redraws every row of that project; it is the project's
  // setting, not the instance's.
  // Staged on the pick, written by Apply: the same shape as the route line
  // above it, and as every other setting on the page.
  el.querySelectorAll("[data-dmref]").forEach(sel => sel.onchange = () => {
    const key = sel.dataset.dmref;
    const row = sel.closest("[data-inst]");
    const saved = (list?.instances || []).find(
      x => `${x.project}|${x.instance}` === key)?.ref || "";
    if (sel.value === saved) delete dmRefDraft[key];
    else dmRefDraft[key] = sel.value;
    const b = row?.querySelector("[data-dmrefapply]");
    if (b) b.disabled = sel.value === saved;
  });
  el.querySelectorAll("[data-dmrefapply]").forEach(btn => btn.onclick = async () => {
    const key = btn.dataset.dmrefapply;
    const [project, instance] = key.split("|");
    const ref = dmRefDraft[key];
    if (ref === undefined) return;
    busy(btn, "Applying");
    try{
      const r = await postJSON("/api/devapp", {project, instance, action: "ref", ref});
      const j = await r.json();
      if (j.error){ notify(j.error, true); return; }
      delete dmRefDraft[key];
      notify(ref ? `${project}/${instance} builds from ${ref} now`
                 : `${project}/${instance} builds from the project's own checkout again`);
      dockerList = null; dockerRev++; loadDocker();
    }catch(e){ notify("the branch: " + e, true); }
    finally{ if (btn.isConnected) unbusy(btn, "Apply"); }
  });
  // Start, stop, restart and the log, on any container the daemon reported,
  // including the ones BuilderBot did not create (R68 steps 1 and 2). The
  // name goes back to the server, which looks it up in a fresh listing
  // before it acts: the rule every executing surface here follows.
  // The node the LIST is about: the notebook reads its project's node, which
  // need not be the one picked on this tab.
  const node = list?.node || dockerNode;
  el.querySelectorAll("[data-ctl]").forEach(b => b.onclick = async () => {
    const what = b.dataset.ctl, ctr = b.dataset.ctr;
    if (what === "stop" && !confirm(`Stop ${ctr}?`)) return;
    busy(b, {start: "Starting", stop: "Stopping", restart: "Restarting"}[what]);
    try{
      const r = await postJSON("/api/dockerctl", {action: what, container: ctr, node});
      const j = await r.json();
      if (j.error) notify(j.error, true); else notify(j.out || `${what} sent`);
    }catch(e){ notify(`${what} ${ctr}: ` + e, true); }
    dockerList = null; loadDocker();
  });
  el.querySelectorAll("[data-logs]").forEach(b => b.onclick = () => dmLogs(b.dataset.logs, list?.node || dockerNode));
  // Start on boot: the tick is a draft, Apply writes it (R122).
  el.querySelectorAll("[data-dmboot]").forEach(cb => cb.onchange = () => {
    const name = cb.dataset.dmboot, was = cb.dataset.was === "1";
    if (cb.checked === was) delete dmBootDraft[name]; else dmBootDraft[name] = cb.checked;
    const b = cb.closest(".dmboot").querySelector("[data-dmbootapply]");
    if (b) b.disabled = cb.checked === was;
  });
  el.querySelectorAll("[data-dmbootapply]").forEach(b => b.onclick = async () => {
    const name = b.dataset.dmbootapply, on = dmBootDraft[name];
    if (on === undefined) return;
    busy(b, "Applying");
    try{
      const j = await (await postJSON("/api/dockerctl", {action: on ? "boot-on" : "boot-off", container: name, node})).json();
      if (j.error){ notify(j.error, true); return; }
      delete dmBootDraft[name];
      notify(j.out || (on ? `${name} starts on boot` : `${name} no longer starts on boot`));
      dockerList = null; dockerRev++; loadDocker();
    }catch(e){ notify("start on boot: " + e, true); }
    finally{ if (b.isConnected) unbusy(b, "Apply"); }
  });
  // Which project a row belongs to: staged on the pick, written by Apply.
  const ownSaved = key => (key.startsWith("ctr:")
    ? (list?.containers || []).find(c => (c.name || c.id) === key.slice(4))
    : (list?.instances || []).find(x => `inst:${x.project}|${x.instance}` === key))?.owner || "";
  el.querySelectorAll("[data-dmown]").forEach(sel => sel.onchange = () => {
    const key = sel.dataset.dmown;
    if (sel.value === ownSaved(key)) delete dmOwnDraft[key];
    else dmOwnDraft[key] = sel.value;
    const b = sel.parentElement.querySelector("[data-dmownapply]");
    if (b) b.disabled = sel.value === ownSaved(key);
  });
  el.querySelectorAll("[data-dmownapply]").forEach(btn => btn.onclick = async () => {
    const key = btn.dataset.dmownapply, owner = dmOwnDraft[key];
    if (owner === undefined) return;
    const other = key.startsWith("ctr:");
    const [project, instance] = other ? [] : key.slice(5).split("|");
    const what = other ? key.slice(4) : (list?.instances || []).find(
      x => x.project === project && x.instance === instance)?.name || project;
    busy(btn, "Applying");
    try{
      const r = await postJSON(other ? "/api/dockerctl" : "/api/devapp", other
        ? {action: "owner", container: key.slice(4), owner, node}
        : {action: "owner", project, instance, owner});
      const j = await r.json();
      if (j.error){ notify(j.error, true); return; }
      delete dmOwnDraft[key];
      notify(owner ? `${what} belongs to ${owner} now` : `${what} belongs to no project now`);
      dockerList = null; dockerRev++; loadDocker();
    }catch(e){ notify("the project: " + e, true); }
    finally{ if (btn.isConnected) unbusy(btn, "Apply"); }
  });

  // Built from: staged on the pick, moved by Move, asked first since what it
  // builds from changes.
  el.querySelectorAll("[data-dmmove]").forEach(sel => sel.onchange = () => {
    const key = sel.dataset.dmmove, from = key.split("|")[0];
    if (sel.value === from) delete dmMoveDraft[key]; else dmMoveDraft[key] = sel.value;
    const b = sel.parentElement.querySelector("[data-dmmoveapply]");
    if (b) b.disabled = sel.value === from;
  });
  el.querySelectorAll("[data-dmmoveapply]").forEach(btn => btn.onclick = async () => {
    const key = btn.dataset.dmmoveapply, to = dmMoveDraft[key];
    if (!to) return;
    const [project, instance] = key.split("|");
    const what = (list?.instances || []).find(
      x => x.project === project && x.instance === instance)?.name || project;
    if (!confirm(`Move ${what} to ${to}? It keeps its name, env and data, and builds from ${
        to}'s tree from its next rebuild.`)) return;
    busy(btn, "Moving");
    try{
      const r = await postJSON("/api/devapp", {action: "move", project, instance, to});
      const j = await r.json();
      if (j.error){ notify(j.error, true); return; }
      delete dmMoveDraft[key];
      notify(`${what} is ${to}'s now` + (j.dropped_ref
        ? `; it built from ${j.dropped_ref}, which was ${project}'s branch, and now builds from ${to}'s checkout` : ""));
      dockerList = null; dockerRev++; loadDocker();
    }catch(e){ notify("move: " + e, true); }
    finally{ if (btn.isConnected) unbusy(btn, "Move"); }
  });

  // The words on the row are a way in to where the setting lives now.
  el.querySelectorAll("[data-dmtestgo]").forEach(a => a.onclick = e => {
    e.preventDefault();
    // The project's settings are its notebook's Settings view (R119 step 3):
    // this clicked the row's settings button, which went with it.
    openProjectSettings(a.dataset.dmtestgo);
  });
  // The route is saved on Apply, not on the pick (docs/design-language.md,
  // Settings): a pick wakes the button when it differs from what is saved.
  el.querySelectorAll("[data-route]").forEach(sel => sel.onchange = () => {
    const row = sel.closest("[data-inst]");
    const d = dmRouteDraft[row.dataset.inst] || (dmRouteDraft[row.dataset.inst] = {});
    d[sel.dataset.route] = sel.value;
    const dirty = [...row.querySelectorAll("[data-route]")].some(x => x.value !== x.dataset.was);
    if (!dirty) delete dmRouteDraft[row.dataset.inst];
    const b = row.querySelector("[data-routeapply]");
    if (b) b.disabled = !dirty;
  });
  el.querySelectorAll("[data-routeapply]").forEach(btn => btn.onclick = async () => {
    const row = btn.closest("[data-inst]");
    const [project, instance] = row.dataset.inst.split("|");
    const sel = row.querySelector('[data-route="mode"]');
    const mode = sel?.value || "lan";
    const port = row.querySelector('[data-route="port"]')?.value || "";
    if (mode === "funnel" && sel.dataset.was !== "funnel" && !confirm(
        `Open ${project}/${instance} to the internet?\n\nAnyone with the link can reach the port until the route goes back to lan.`)){
          row.querySelectorAll("[data-route]").forEach(x => { x.value = x.dataset.was; });
          btn.disabled = true; delete dmRouteDraft[row.dataset.inst]; return; }
    delete dmRouteDraft[row.dataset.inst];
    busy(btn, "Applying");
    try{
      const r = await postJSON("/api/devapp", {project, instance, action:"route", mode, port});
      const j = await r.json();
      if (j.error) notify(j.error, true);
    }catch(e){ notify("route: " + e, true); }
    dockerList = null; dockerRev++; loadDocker();
  });
}

// Grouped by the PROJECT each row belongs to (the operator, 24 Sep): a
// project's containers together under its name, the groups in alphabetical
// order, and what belongs to no project last. In each, BuilderBot's own
// containers first and then the others, by name. Where a row came from
// (built from a project, written here, or started by somebody else) is said
// on the row itself, since that is what decides what can be done to it.
function dmGroupsHtml(ins, cs, job, blind){
  // A project's heading wears its own color when it has one; `null` is
  // the No project heading, which wears none.
  const head = (t, sub, tone) => `<div class="field dmgroup${tone === null ? " none" : ""}"${
    tone ? ` style="--gc:${tone}"` : ""}><b>${esc(t)}</b>${
    sub ? `<span class="dim">${esc(sub)}</span>` : ""}</div>`;
  const byName = (a, b) => a.localeCompare(b, undefined, {sensitivity: "base"});
  const owners = [...new Set([...ins, ...cs].map(r => r.owner || ""))]
    .filter(Boolean).sort(byName);
  const group = o =>
    dmRowsHtml(ins.filter(d => (d.owner || "") === o).sort((a, b) => byName(a.name, b.name)), job, blind)
    + dmOtherRowsHtml(cs.filter(c => (c.owner || "") === o)
        .sort((a, b) => byName(a.name || a.id, b.name || b.id)));
  const loose = [...ins, ...cs].some(r => !r.owner);
  // A deleted project's containers keep its name until it is restored from
  // the trash, or they are moved or given to another project (8 Oct).
  const gone = o => [...ins, ...cs].some(r => r.owner === o && r.owner_gone);
  return owners.map(o => gone(o)
      ? head(`${o} (deleted)`, "restore it from the trash, or Move these to another project", null) + group(o)
      : head(o, "", colorTone(projectColor(o))) + group(o)).join("")
    + (loose ? head("No project", "no Claude session sees these", null) + group("") : "");
}

// A container BuilderBot did not start: what the daemon says about it,
// started, stopped and restarted by name, and put under a project on its row.
// Start on boot (R122): a switch on a row, a draft until its Apply, as every
// setting here is. `name` is what the server acts on (a container, or an
// instance meaning all its containers), `on` what the daemon says now.
let dmBootDraft = {};
function dmBootLine(name, on){
  if (!mayDocker()) return "";
  const want = name in dmBootDraft ? dmBootDraft[name] : on;
  // The Project line's shape, its Apply beside it (.dmowner's rules).
  return `<div class="sub dmowner dmboot"><label class="ndcap"><input type="checkbox" data-dmboot="${esc(name)}"
      data-was="${on ? "1" : ""}"${want ? " checked" : ""}> Start on boot</label>
    <button type="button" data-dmbootapply="${esc(name)}"${want === on ? " disabled" : ""}
      title="docker's restart policy: unless-stopped when ticked, no when not">Apply</button></div>`;
}

function dmOtherRowsHtml(cs){
  return cs.map(c => `
    <div class="row stack2 off dmother" data-ctr="${esc(c.name || c.id)}">
      <div class="grow">
        <div class="name">${esc(c.name || c.id)} <span class="pill" title="not started by BuilderBot">not ours</span></div>
        <div class="sub">${esc(c.image)}</div>
        <div class="sub ${c.state === "running" ? "ok" : ""}">${esc(c.status || c.state)}${
          c.project ? ` · ${esc(c.project)}${c.service ? "/" + esc(c.service) : ""}` : ""}</div>
        ${c.ports.length ? `<div class="sub">${c.ports.map(esc).join(" · ")}</div>` : ""}
        ${dmOwnerLine(c, "ctr:" + (c.name || c.id))}${dmGrantLine(c, true)}
        ${dmBootLine(c.name || c.id, !!c.boot)}
      </div>
      <div class="actbar dmacts">
        ${!mayDocker() ? "" : `<button type="button" data-ctl="${
          c.state === "running" ? "stop" : "start"}" data-ctr="${esc(c.name || c.id)}"
          title="${c.state === "running" ? "Stop" : "Start"} it: docker ${c.state === "running" ? "stop" : "start"} ${esc(c.name || c.id)}">${
          c.state === "running" ? "Stop" : "Start"}</button>
        <button type="button" data-ctl="restart" data-ctr="${esc(c.name || c.id)}"${
          c.state === "running" ? "" : " disabled"}
          title="Restart it: docker restart ${esc(c.name || c.id)}">Restart</button>`}
        ${!mayDocker() ? "" : `<button type="button" data-logs="${esc(c.name || c.id)}"
          title="the last ${esc(String(400))} lines it printed">Log</button>`}
      </div>
    </div>`).join("");
}

function renderDockerInto(i){
  const el = $("doc" + i);
  if (!el) return;
  el.classList.add("flush");
  // An answer on its way is not a blank page: a build makes the daemon's
  // ps slow, and the operator watched the whole tab turn to "loading" for
  // the length of a build. The last answer for this node stays on screen
  // with a note, and the new one repaints when it lands (B125).
  if (!dockerList && dockerSeen[dockerNode || ""]) dockerList = dockerSeen[dockerNode || ""];
  if (!dockerList){ el.innerHTML = `<div class="loading">loading…</div>`; return; }
  // The daemon did not answer; it is off, it is not a sandbox VM, or the VM
  // is not running. This used to end here, in one error line with no rows: the
  // page threw away everything it could still honestly say, which is most of
  // it. What an instance IS lives on this side (its name, its project, what it
  // was built from, what its env still wants); only whether it is RUNNING is
  // the daemon's to know. So the rows are drawn from the store, grayed, and
  // say nothing about their state: an unreachable daemon is not evidence that
  // anything stopped.
  // Three ways to be blind, and the poll's is the one that outlives a fetch:
  // a list read while the daemon was up is stale the moment the poll says it
  // is down, and going on showing "running" from it would be the page's own
  // memory presented as the daemon's answer.
  // The poll's verdict is about the DEFAULT node, so it speaks for this view
  // only while this view IS the default one. Computed once, because `blind`
  // and the gate below both used to ask and only one of them narrowed it.
  const pollSays = dmPollSays();
  const blind = dmBlind();
  const ins = dockerList.instances || [];
  const cs = dockerList.containers || [];
  const job = dockerJob();
  const rows = dmGroupsHtml(ins, cs, job, blind);
  // Its own class rather than the projects tab's: the two look alike and a
  // selector that matched both would be a test passing on the wrong tab.
  // Said in words at the top, not only in the tooltips below: a tooltip is
  // not reachable on a phone, and "why is everything grayed out" should be
  // answered by looking rather than by hovering.
  // Why everything is grayed, in words at the top. The poll's sentence when it
  // has one; otherwise the daemon's own words from the call this page just
  // made, which is the case the poll cannot see: a VM that went away inside
  // the availability memo.
  // The poll's verdict is about the DEFAULT node; a picked node answers for
  // itself through its own overview. Mixing them gated node B behind node
  // A's absence, which is the one wrong answer a picker can give.
  // WHAT SWITCHES THE BUTTONS OFF is whether this node can be ACTED on, which
  // is not whether this controller can see what is running there. On an agent
  // node compose goes to the agent and runs against that machine's own
  // socket, so a controller that cannot ssh in changes nothing about whether
  // Up works, and gating on the listing ghosted Up, Down, Rebuild and Send
  // on a node where all four would have worked (B111). A listing that failed
  // still grays the ROWS, because what they would claim about running and
  // stopped is exactly what nobody asked.
  const off = pollSays
    || (dockerList.on === false ? (dockerList.why || "the daemon did not answer") : "");
  // Said, not switched off: a listing that failed is worth a line, and the
  // line has to say that the buttons under it still work.
  const note = off || (dockerList.error
    // The error's own full stop comes off before the clause is joined on:
    // "...does not know.: the rows cannot say" was on a walk's screenshot.
    ? `Docker did not answer: ${String(dockerList.error).replace(/\.\s*$/, "")}. What is running `
      + `is unknown; the controls still work`
    : "");
  // Which daemon this is, stated rather than inferred: the node picked
  // above names it, and saying which machine the buttons below act on is
  // worth a line whatever the arrangement.
  // The PICKED node's own answer, not the poll's: the poll is about the
  // default node, so on any other one this line named a machine the tab was
  // not talking to, in an address, which reads as proof.
  const src = dockerList?.src || state?.docker || {};
  const srcLine = !note && src.kind
    ? `<div class="dmsrc">${src.agent ? `on ${esc(src.kind)}, through its agent`
                                       : `on ${esc(src.kind)} at <code>${esc(src.where)}</code>`}${
        // A mapped path this container does not have. Not a fault: it can be a
        // share the daemon mounts and BuilderBot has no business reading. It is
        // said because nothing else here will ever act on it, and a line of
        // configuration that does nothing should not look like it does.
        (src.strays || []).length
          ? `<br><span class="dim">${esc((src.strays || []).join(", "))} ${
              src.strays.length > 1 ? "are" : "is"} mapped but not mounted here</span>` : ""}</div>`
    : "";
  // Slow, not merely in flight: dockerFetching alone is true for the whole
  // of every fetch, and the timer in loadDocker is what decides it is worth
  // saying. A listing the server itself marked stale wears the same class
  // without the word: it is the last answer, and nothing is on its way that
  // the next revision will not bring.
  const slow = dockerFetching && dmSlow;
  // The picker: every node, online or not: an offline node's view is its
  // last-known list in the ghosted state the blind path draws.
  // One tab, re-rendered per pick (docs/nodes.md §13), never a tab per node.
  // The one node switcher (page-docs.js nodePick, R121 step 5), in the bar
  // the other node-scoped tabs wear: the picker at the left, Refresh at the
  // right, drawn whenever there is a node so the tab says whose daemon it is.
  const dnodes = (nodesList || []).filter(n => n.kind !== "local");
  if (nodesList === null) loadNodes();
  const picker = `<div class="field histbar docbarrow dmpick">${
      nodePick("dmNode", dnodes, dockerNode || dnodes[0]?.id)}<span class="sp"></span>
      <button type="button" id="bDockerRe" title="ask the daemon again">Refresh</button>${
      slow ? `<span class="dim dmfresh">refreshing…</span>` : ""}</div>${
      // Adding at the top, in the add band every view adds with, where a
      // phone finds it without scrolling past every container (R119 step 5).
      mayDocker() ? `<div class="field"><div class="addbar" data-add="container">
        <button type="button" id="bDockerNew">New container</button></div></div>` : ""}`;
  // What a session is waiting on, above everything else: somebody is blocked
  // on these, and this is the tab whose dial sent them here. The bell carries
  // them too, the way root asks sit on the Nodes tab and in the bell.
  const asks = (typeof ph !== "undefined" && ph?.asks || [])
    .filter(a => a.kind === "rebuild");
  const askRows = asks.map(a => `<div class="row dmask">
      <div class="grow"><div class="name">${esc(askVerb(a))}: ${esc(a.why)}</div>
        <div class="phcmd">bb ${esc(a.cmd.join(" "))}</div>
        <div class="sub">${esc(a.asker ? a.asker + "'s session in " + (a.project || "a project")
                                       : a.project || "a session")} asks to ${esc(askVerb(a))} it · ${
          a.left > 60 ? `${Math.floor(a.left / 60)} min left to answer`
                      : `${a.left}s left to answer`}</div></div>
      <span class="acts">
        <button type="button" data-rdeny="${a.id}">Deny</button>
        <button type="button" class="primary" data-rallow="${a.id}">Allow</button>
      </span></div>`).join("");
  // `dmstale` while the rows are the last answer and a new one is on its
  // way: what a reader waiting on a refresh looks at, and what the note
  // below says in words.
  el.innerHTML = `<div class="doctab dmtab${slow || dockerList?.stale ? " dmstale" : ""}">${picker}${askRows}${note
      ? `<div class="empty">${esc(note)}</div>` : srcLine}${
    // Blind, the list is what is on record here rather than what is on the
    // daemon, and "nothing on this daemon yet" would be a claim about a
    // machine nobody just asked.
    rows || `<div class="empty">${blind
      ? "nothing on record here: an instance appears once it has been sent"
      : "nothing on this daemon yet"}</div>`}
    </div>`;
  gateDocker(el, off);
  // The asks answer through the phone's endpoint, which holds the one list of
  // them; phFetch redraws this tab when the answer comes back.
  el.querySelectorAll("[data-rallow]").forEach(b => b.onclick = () => {
    b.disabled = true; b.textContent = "starting";
    phFetch({action: "allow", id: Number(b.dataset.rallow)});
  });
  el.querySelectorAll("[data-rdeny]").forEach(b => b.onclick = () =>
    phFetch({action: "deny", id: Number(b.dataset.rdeny)}));
  const b = el.querySelector("#bDockerRe");
  if (b) b.onclick = () => { dockerList = null; dockerRev++; drawPanes(); loadDocker(); };
  const pk = el.querySelector("#dmNode");
  if (pk) pk.onchange = () => {
    dockerNode = pk.value;
    dockerNodeKeep();
    // The last-known answer first: instant, honestly stale (the blind path
    // says so), and a fresh ask behind it.
    dockerList = dockerSeen[dockerNode] || null;
    dockerRev++; drawPanes(); loadDocker();
  };
  const nb = el.querySelector("#bDockerNew");
  if (nb) nb.onclick = openNewContainer;
  // The wiring, fetched when the fold is opened and not before. It needs the
  // compose file parsed, which is the one thing overview() refuses to do for
  // every instance at once, and it is the thing you want occasionally, which
  // is what a fold is for. Rendered the same way the artifact row renders it:
  // the container's side on the left, the daemon's on the right, and an arrow
  // saying which way a mount goes.
  tipify(el);
  // The summary's own click, not the toggle: <details> opens instantly by
  // construction, so the flag has to be driven by slideDetails: the same
  // helper the notebook's folds already use, rather than watched afterwards.
  // wireSections first, for the remembered open state; then the click is
  // rebound, because this fold also has to fetch what it is about to show.
  dmWireRows(el, dockerList);
}

// ---- new project / link to a git host ----------------------------------
// One dialog, three modes, one table. `init` and `clone` feed /api/create;
// `link` points an existing repo at an empty one via /api/link. The
// table is the whole difference between the modes, which fields show, what
// the button says, where it posts, so a new mode is a row, not a hunt
// through branches. The server re-validates everything; this side only
// catches the obvious before a round-trip, and keeps the dialog open on
// failure so nothing typed is lost.

// ---- no daemon, no Docker buttons ---------------------------------------

// The controls that act on the daemon, in one list. Not the ones that only
// read or explain: Refresh is how you retry after wiring one up, Edit and Env
// open a compose file that is a file whether or not anything can run it, and
// the manager tab itself is where the reason is written in words: disabling
// the way to READ a diagnosis is how you get a dashboard that has gone quiet
// for no visible cause.
//
// REMOVE IS NOT ONE OF THEM, and that is the correction: removing is this
// side's own record, with a `down` in front of it as a courtesy. Gating it on
// the daemon left a row on a machine that had gone away removable by nobody:
// the one state a list must not have, since the row is the only control over
// the thing it names. It stays live, the server takes the record either way,
// and the confirmation says which of the two halves will happen.
// The new-project dialog that followed this list is tab-projects.js now; its fields and its submit are wired further down.
const DOCKER_ACTS = '[data-dm="up"],[data-dm="down"],'
                  + '[data-dm="rebuild"],'
                  + '#devSend,#bDockerNew';
