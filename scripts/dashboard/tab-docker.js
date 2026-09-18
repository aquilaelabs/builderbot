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
// and every node's rows were greyed by the default node's silence again, with
// the guard sitting right there looking like it worked. Failing open costs
// nothing: the tab's own overview reports its node's daemon, and that is what
// greys a row whose daemon is genuinely down.
const dmPollSays = () => {
  const about = state?.docker?.node;
  if (dockerNode && about !== dockerNode) return "";
  return dockerWhy();
};

// Whether this list knows what is actually running. One function because the
// rows' ghosting and Remove's confirmation are the same question asked twice,
// and two copies of it would drift.
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
    // dev row does not and keeps the native tooltip its neighbours use. Which
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

function openDocker(){
  const t = dockerTab();
  if (!dockerNode && t?.arg && t.arg !== "__docker") dockerNode = t.arg;
  openTab({kind: "docker", arg: dockerNode || "__docker", label: "Docker"});
  loadDocker();
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
async function loadDocker(){
  const asked = dockerNode;
  const ask = ++dockerAsk;
  dockerFetching = true;
  let got;
  try{
    got = await (await fetch("/api/docker"
      + (asked ? "?node=" + encodeURIComponent(asked) : ""))).json();
  }catch(e){ got = {error: String(e), containers: []}; }
  // An answer for a node the operator has already picked away from must not
  // repaint the view it no longer belongs to; it lands in that node's cache
  // and nothing else.
  dockerSeen[got.node || asked || ""] = got;
  if (ask === dockerAsk) dockerFetching = false;
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
  // tab is the layout's business, and packages already refreshes this way.
  drawPanes();
}

// Naming a container from a project. The name says WHICH of that project's
// containers this is; what it is built from is settled by the project, which
// is why there is nothing else to fill in here.
let dnFor = null;

function openSendToDocker(project){
  dnFor = project;
  $("dnTitle").textContent = "New container from " + project;
  $("dnName").value = "";
  $("dnErrWrap").hidden = true;
  $("dnPreview").hidden = true;
  $("dnGo").disabled = false; $("dnGo").textContent = "Create";
  $("dnHint").textContent =
    "It is built from " + project + "'s codebase, and rebuilding it takes "
    + "whatever that codebase says then. A project can have several: give "
    + "each one a name you will recognise in the manager; anything, including "
    + "a project's name, as long as no other container has it.";
  $("dnEnvField").hidden = true;
  $("dnEnv").value = "";
  fillUnderSelect($("dnUnder"), project);
  fillNodeSelect($("dnNode"), $("dnNodeField"),
                 state?.projects?.find(p => p.name === project)
                   ?.prefs?.node || dockerNode);
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
        "Seeded from " + project + "'s .env.example, comments and all. Saved "
        + "for this container alone when you press Create, so the first build "
        + "has it.";
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
function fillNodeSelect(sel, wrap, prefer){
  // Every node, not a subset: a node does everything for the projects bound
  // to it, so there is nothing to narrow by (docs/nodes.md §13).
  const dnodes = (nodesList || []).filter(n =>
    n.kind !== "local" && n.state !== "retired");
  // ...and drawn again when they land: loadNodes repaints only a Nodes tab,
  // so a draw here during a node-list reload lost the picker until something
  // else moved dockerRev (B69's nodes.mjs sibling).
  if (nodesList === null) loadNodes().then(() => { dockerRev++; drawPanes(); });
  wrap.hidden = dnodes.length < 2;
  // An agent node carries its heartbeat's numbers, and this is the picker
  // the design says they belong beside (docs/nodes.md §9): the choice of
  // where to run a container is made on how busy the machine is.
  sel.innerHTML = dnodes.map(n => {
    const s = n.kind === "agent" && n.live && n.reported?.sample;
    const nums = s ? ` · cpu ${s.cpu_pct}% · ${Math.round(s.mem_used_mb / 1024 * 10) / 10}/${
        Math.round(s.mem_mb / 1024)}GB` : n.kind === "agent" ? " · quiet" : "";
    return `<option value="${esc(n.id)}"${n.id === prefer ? " selected" : ""}>${
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
  $("dnGo").disabled = true; $("dnGo").textContent = "Creating…";
  try{
    const r = await fetch("/api/devapp", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({project, action:"new", instance:name,
                            for: $("dnUnder").value,
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
// ...and the same for the rebuild dial, per project. Nothing on a tab takes
// effect until Apply (docs/design-language.md, Settings): this wrote on the
// pick when it was a switch, which is a control that cannot be reconsidered
// and reads differently from every other setting on the page.
const dmGrantDraft = {};
// Where a session's tests run, per project (roadmap R48, step 3): the same
// draft-then-Apply shape as the dial above it. `either` is the default; on
// `only`, bb test refuses when the container is down rather than running on
// the node, which is the whole point for a project that IS the container.
const DEVTEST_MODES = [["either", "in it when it is up, else on the node"],
                       ["only", "only in it, never on the node"]];
const dmTestDraft = {};
const devTestMode = name => ((state?.projects || []).find(p => p.name === name)?.prefs?.devtest
                             ? "only" : "either");

function dmRouteLine(d){
  const r = d.route;
  const draft = dmRouteDraft[`${d.project}|${d.instance}`] || {};
  const mode = draft.mode ?? r?.mode, port = String(draft.port ?? r?.port ?? "");
  const dirty = (draft.mode != null && draft.mode !== r?.mode)
             || (draft.port != null && String(draft.port) !== String(r?.port ?? ""));
  if (!r || (!r.ports?.length && r.mode === "lan" && !r.url)) return "";
  const link = r.url
    ? `<a href="${esc(r.url)}" target="_blank" rel="noreferrer"${r.ready ? "" : ' class="dim"'}>${esc(r.url)}</a>`
    : `<span class="dim">no address</span>`;
  const modes = [["lan", "lan: the node's address"],
                 ["funnel", r.funnel_ok ? "funnel (a public https URL via Tailscale" : "funnel) needs tailscale on the node"],
                 ["public", "public, not built"]];
  return `<div class="sub dmroute">${link}${r.why ? ` <span class="dim">· ${esc(r.why)}</span>` : ""}
    <select data-route="mode" data-was="${esc(r.mode)}" aria-label="route" title="how this instance is reached">${
      modes.map(([v, l]) => `<option value="${v}"${v === mode ? " selected" : ""}${
        v === "public" || (v === "funnel" && !r.funnel_ok) ? " disabled" : ""}>${esc(l)}</option>`).join("")}</select>${
    r.ports?.length > 1 ? `<select data-route="port" data-was="${esc(String(r.port))}" aria-label="port" title="which published port">${
      r.ports.map(p => `<option value="${p}"${String(p) === port ? " selected" : ""}>:${p}</option>`).join("")}</select>` : ""}
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
      helpIcon("The build comes from a worktree of that branch beside the project, "
        + "so the project's own checkout is left where it is and nobody else's "
        + "session moves. Its containers, env and data are unchanged; only what "
        + "the next build is made of.")}</label>
    <select id="${esc("dmr-" + key)}" data-dmref="${esc(key)}" aria-label="which branch to build">
      <option value=""${saved ? "" : " selected"}>whatever the project is on</option>${
      refs.map(b => `<option value="${esc(b)}"${b === pick ? " selected" : ""}>${
        esc(b)}</option>`).join("")}</select>
    <button type="button" data-dmrefapply="${esc(key)}"${
      pick === saved ? " disabled" : ""} title="build this container from that branch from now on"
      >Apply</button></div>`;
}

function dmGrantLine(d){
  // Not for a container written here: its compose file IS the thing, so there
  // is no project codebase for a session to rebuild it from.
  if (d.source === "file" || !mayDocker()) return "";
  const saved = devClaudeMode(d.project);
  const pick = dmGrantDraft[d.project] ?? saved;
  return `<div class="sub dmgrant"><label for="${
      esc(`dmg-${d.project}`)}">Claude may rebuild${
    helpIcon(`A session in ${d.project} builds this from the project's codebase `
      + `and brings it up: on ask it says what the rebuild is for and waits for `
      + `you, on auto it just runs. Making a container, removing one, Up, Down `
      + `and Env are yours whatever this says, and it covers every instance of `
      + `${d.project}.`)}</label>
    <select id="${esc(`dmg-${d.project}`)}" data-dmclaude="${esc(d.project)}"
            data-was="${esc(saved)}"
            aria-label="whether a session may rebuild ${esc(d.project)}">${
      DEVBUILD_MODES.map(([v, l]) => `<option value="${v}"${
        v === pick ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
    <button type="button" data-dmclaudeapply="${esc(d.project)}"${
      pick === saved ? " disabled" : ""} title="save who may rebuild ${
      esc(d.project)}'s containers">Apply</button></div>`;
}

function dmTestLine(d){
  if (d.source === "file" || !mayDocker()) return "";
  const saved = devTestMode(d.project);
  const pick = dmTestDraft[d.project] ?? saved;
  return `<div class="sub dmgrant"><label for="${
      esc(`dmt-${d.project}`)}">Claude tests${
    helpIcon(`Where bb test runs for ${d.project}. Inside this container `
      + `whenever it is up either way; on "only" a container that is down is `
      + `a refusal naming it, and nothing runs on the node, so a suite that `
      + `tests ${d.project} cannot disturb the ${d.project} it runs beside. `
      + `A stale container then tests stale code: the rebuild dial governs `
      + `testing too.`)}</label>
    <select id="${esc(`dmt-${d.project}`)}" data-dmtest="${esc(d.project)}"
            data-was="${esc(saved)}"
            aria-label="where a session runs ${esc(d.project)}'s tests">${
      DEVTEST_MODES.map(([v, l]) => `<option value="${v}"${
        v === pick ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
    <button type="button" data-dmtestapply="${esc(d.project)}"${
      pick === saved ? " disabled" : ""} title="save where ${
      esc(d.project)}'s tests run">Apply</button></div>`;
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
      `Remove ${project}/${instance} from the manager?\n\n`
      // Which of the two halves is actually going to happen. A row whose
      // daemon is not answering loses the down, and somebody removing one
      // should be told that before they press it rather than read it
      // afterwards.
      + (dmBlind()
          ? `Its daemon does not answer, so nothing can be taken down: the row `
            + `goes and anything running over there keeps running. `
          : `It is taken down first. `)
      + `Its env file and its data directory stay, so sending it again under `
      + `the same name finds them.\n\n`
      + `The project keeps its Artifacts tab either way; that is where it `
      + `comes back from.`)) return;
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
    if ((st.missing_env || []).length && act === "up"){
      notify(`the env is missing ${st.missing_env.join(", ")}: press Env`, true);
      return;
    }
    if (act === "rebuild" && !confirm(
        (st.built_rev ? `Rebuild ${project}/${instance}?\n\nBuilds the image, then down and up. `
                      : `Build ${project}/${instance}?\n\nBuilds the first image and brings it up. `)
        + "If the build finds new env settings it stops before up, and the Env "
        + "editor will hold your old values in comments.")) return;
    if (!st.risks_ack){
      if (!confirm("This compose file asks for more than its own directory:"
          + "\n\n" + (st.risks || []).map(x => "\u2022 " + x).join("\n")
          + "\n\nA container it starts can reach those. Start it anyway?")) return;
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
    const lines =
      (st.ports || []).map(p => {
        const at = `${daemonHost()}:${p.published || ""}`;
        // A link only where there is something to open: a port with no
        // published side is picked at start and has no address yet, and a
        // link to a udp port is a link to nothing.
        const body = p.published && /tcp/i.test(p.proto || "tcp")
          ? `<a href="http://${esc(at)}/" target="_blank" rel="noreferrer">${esc(at)}</a>`
          : esc(p.published ? at : "picked at start");
        return `<div class="dim li wport"><span class="wt">${esc(p.target)}:${
          esc(p.proto)}</span> <span class="wa">←</span> ${body}</div>`;
      }).join("")
      + (st.mounts || []).map(m => `<div class="dim li wmount"><span class="wt">${
        esc(m.target)}</span> <span class="wa">${m.ro ? "←" : "↔"}</span> ${
        esc(m.source)}</div>`).join("");
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
    "Its name is what the compose project is called, so it does not change "
    + "here: remove it and write it again under another one.";
  $("cNodeField").hidden = true;   // where it runs is not an edit either
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

// The "show under" picker: every project this account sees, none first.
function fillUnderSelect(sel, picked){
  const names = (state?.projects || []).map(p => p.name).sort((a, b) => a.localeCompare(b));
  sel.innerHTML = `<option value="">none</option>` + names.map(n =>
    `<option value="${esc(n)}"${n === picked ? " selected" : ""}>${esc(n)}</option>`).join("");
}

function openNewContainer(){
  cEditing = null;
  $("cName").disabled = false;
  $("cName").value = "";
  fillUnderSelect($("cUnder"), "");
  // Left EMPTY, both of them. The shape each wants is on the field as a
  // placeholder, which shows the same thing and cannot be submitted: seeded
  // as values, an example compose for a radarr nobody asked for was one
  // unread click from being created under whatever name was typed.
  $("cYml").value = $("cEnv").value = "";
  // Created on the node the manager is looking at, unless picked otherwise.
  fillNodeSelect($("cNode"), $("cNodeField"), dockerNode);
  $("cErrWrap").hidden = true;
  $("cGo").disabled = false; $("cGo").textContent = "Create";
  cSeg("yml");
  $("cNameHint").textContent =
    "Its own name, not a project's. It becomes the compose project on the "
    + "sandbox VM, which is what the manager lists it by.";
  $("cmodal").hidden = false;
}

let cTab = "yml";                 // which pane the segment is showing

function cSeg(which){
  cTab = which;
  $("cTabYml").classList.toggle("on", which === "yml");
  $("cTabEnv").classList.toggle("on", which === "env");
  $("cYmlField").hidden = which !== "yml";
  $("cEnvField").hidden = which === "yml";
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
  $(which === "yml" ? "cYmlField" : "cEnvField").animate(
    [{transform: `translateX(${which === "env" ? "18px" : "-18px"})`, opacity: 0},
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
                              ? "" : $("cNode").value),
                            for: editing ? "" : $("cUnder").value,
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
          + `That takes it down and brings it back up. Cancel keeps the change `
          + `on disk: the row will offer Rebuild whenever you want it.`)){
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
  // Nothing was asked, so nothing is claimed. What it was built from is still
  // true (that is a record on this side) and it is the one fact worth
  // carrying into a listing nobody can act on.
  if (blind)
    return d.built_rev
      ? `${dmBuilt(d)}: the daemon is not answering, so whether it is up is
         unknown`
      : "never built: the daemon is not answering";
  if (busy) return esc(job.step || "working") + '<span class="dots"></span>';
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
            : d.running ? "running" : d.exists ? "stopped" : "down"})</span></div>
        <div class="sub">${d.source === "file"
          ? `compose written here`
          : `${esc(d.project)} · ${esc(d.instance)}`}${
          d.for && d.for !== d.project ? ` · for ${esc(d.for)}` : ""}</div>
        </div>
        ${d.ports.length ? `<div class="sub dmports">${
          d.ports.map(esc).join(" · ")}</div>` : ""}
        ${(d.services || []).length > 1 ? `<div class="sub dmsvcs">${d.services.map(c =>
          `<span class="dmsvc ${c.state === "running" ? "ok" : finished(c) ? "" : "dim"}" title="${esc(c.image || "")}">${
            esc(c.service || c.name)}: ${finished(c) ? `finished (${esc(c.status)})` : esc(c.status || c.state)}${
            (c.ports || []).length ? ` (${c.ports.map(esc).join(", ")})` : ""}</span>`).join("<br>")}</div>` : ""}
        ${dmRouteLine(d)}
        <div class="dmsettings">${dmRefLine(d)}${dmGrantLine(d)}${dmTestLine(d)}</div>
        ${d.await_env ? `<div class="sub warn">built: fill in the env, then Up</div>` : ""}
        ${busy || (mine && job.error)
          // What it is actually doing, live. The step word above says the
          // phase (building, starting) and this says what the phase is
          // spending its time on, which for a pull is the only way to tell a
          // slow download from a hang. Raw, and deliberately not parsed into a
          // bar: docker rewrites a line per layer per tick, and turning that
          // into a percentage is the thing the packages tab gave up on.
          // Tailed whether or not it is still running. The row only
          // repaints when something moved, so this is not a fight with the
          // reader's scrolling, and the end is where the reason is: a failed
          // job rendered its last 1200 characters scrolled to the TOP, which
          // on anything that pulled an image is the middle of the download
          // and never the error that ended it.
          ? `<pre class="dmlog" data-tail="1">${
              esc((job.log || "").slice(-1200))}</pre>` : ""}
      </div>
      <div class="actbar dmacts">
        <span class="state${!blind && d.running ? " ok" : ""}">${dmState(d, job, mine, busy, blind)}</span>
        ${!mayDocker() ? "" : `<button type="button" data-dm="up" ${
          d.running || busy || (d.missing_env || []).length ? "disabled" : ""}
          title="${(d.missing_env || []).length
            ? "the env is missing " + esc(d.missing_env.join(", "))
            : !d.built_rev
              ? "docker compose up -d: builds the image first, as compose does"
              : "docker compose up -d"}">Up</button>
        <button type="button" data-dm="down" ${!d.exists || busy ? "disabled" : ""}
          title="docker compose down">Down</button>
        ${d.source === "file"
          ? `<button type="button" data-dm="edit"
               title="edit this container's compose file and env">Edit</button>`
          : `<button type="button" data-dm="env"
               title="this container's env file">Env</button>`}
        `}
        ${busy ? `<button type="button" data-dm="abort" ${
            job.aborting ? "disabled" : ""}
            title="stop this build. What is already built is kept: an abort is
for the rest of the work"
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
            title="take it down and drop it from this list. Its env and its data
directory stay, so remaking it under the same name finds them">Remove</button>`}
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
  el.querySelectorAll("[data-dmtest]").forEach(sel => sel.onchange = () => {
    const project = sel.dataset.dmtest;
    if (sel.value === sel.dataset.was) delete dmTestDraft[project];
    else dmTestDraft[project] = sel.value;
    const b = el.querySelector(`[data-dmtestapply="${CSS.escape(project)}"]`);
    if (b) b.disabled = sel.value === sel.dataset.was;
  });
  el.querySelectorAll("[data-dmtestapply]").forEach(btn => btn.onclick = async () => {
    const project = btn.dataset.dmtestapply;
    const mode = dmTestDraft[project];
    if (!mode) return;
    busy(btn, "Applying");
    try{
      const r = await postJSON("/api/prefs", {project, devtest: mode === "only"});
      const j = await r.json();
      if (j.error){ notify(j.error, true); return; }
      delete dmTestDraft[project];
      notify(mode === "only" ? `${project}'s tests run only inside its container now`
             : `${project}'s tests run on the node again when its container is down`);
      refresh();
      dockerRev++; drawPanes();
    }catch(e){ notify("where the tests run: " + e, true); }
    finally{ if (btn.isConnected) unbusy(btn, "Apply"); }
  });
  el.querySelectorAll("[data-dmclaude]").forEach(sel => sel.onchange = () => {
    const project = sel.dataset.dmclaude;
    if (sel.value === sel.dataset.was) delete dmGrantDraft[project];
    else dmGrantDraft[project] = sel.value;
    const b = el.querySelector(`[data-dmclaudeapply="${CSS.escape(project)}"]`);
    if (b) b.disabled = sel.value === sel.dataset.was;
  });
  el.querySelectorAll("[data-dmclaudeapply]").forEach(btn => btn.onclick = async () => {
    const project = btn.dataset.dmclaudeapply;
    const mode = dmGrantDraft[project];
    if (!mode) return;
    busy(btn, "Applying");
    try{
      const r = await postJSON("/api/prefs", {project, devbuild: mode});
      const j = await r.json();
      if (j.error){ notify(j.error, true); return; }
      delete dmGrantDraft[project];
      notify(mode === "auto" ? `a session in ${project} may rebuild its containers`
             : mode === "ask" ? `a session in ${project} will ask you before rebuilding`
             : `rebuilding ${project}'s containers is yours again`);
      refresh();
      dockerRev++; drawPanes();
    }catch(e){ notify("the dial: " + e, true); }
    finally{ if (btn.isConnected) unbusy(btn, "Apply"); }
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
        `Open ${project}/${instance} to the internet?\n\nTailscale Funnel gives it a public `
        + `https URL on the node: anyone with the link can reach the port. Turning the `
        + `route back to lan closes it.`)){
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
  // the daemon's to know. So the rows are drawn from the store, greyed, and
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
  // The dashboard's own first, each with the controls that used to live on the
  // artifact row; this is where they went, and the row now only sends you
  // here. Grouped by nothing: the project is on every line, and a heading per
  // project would put a lot of chrome around lists that are usually one long.
  const rows = dmRowsHtml(ins, job, blind) + cs.map(c => `
    <div class="row stack2 off">
      <div class="grow">
        <div class="name">${esc(c.name || c.id)} <span class="pill">not ours</span></div>
        <div class="sub">${esc(c.image)}</div>
        <div class="sub ${c.state === "running" ? "ok" : ""}">${esc(c.status || c.state)}${
          c.project ? ` · ${esc(c.project)}${c.service ? "/" + esc(c.service) : ""}` : ""}</div>
        ${c.ports.length ? `<div class="sub">${c.ports.map(esc).join(" · ")}</div>` : ""}
      </div>
    </div>`).join("");
  // Its own class rather than the projects tab's: the two look alike and a
  // selector that matched both would be a test passing on the wrong tab.
  // Said in words at the top, not only in the tooltips below: a tooltip is
  // not reachable on a phone, and "why is everything greyed out" should be
  // answered by looking rather than by hovering.
  // Why everything is greyed, in words at the top. The poll's sentence when it
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
  // still greys the ROWS, because what they would claim about running and
  // stopped is exactly what nobody asked.
  const off = pollSays
    || (dockerList.on === false ? (dockerList.why || "the daemon did not answer") : "");
  // Said, not switched off: a listing that failed is worth a line, and the
  // line has to say that the buttons under it still work.
  const note = off || (dockerList.error
    ? `the daemon did not answer: ${dockerList.error}: the rows cannot say `
      + `what is running, though the controls still work through the agent`
    : "");
  // Which daemon this is, stated rather than inferred: the node picked
  // above names it, and saying which machine the buttons below act on is
  // worth a line whatever the arrangement.
  // The PICKED node's own answer, not the poll's: the poll is about the
  // default node, so on any other one this line named a machine the tab was
  // not talking to, in an address, which reads as proof.
  const src = dockerList?.src || state?.docker || {};
  const srcLine = !note && src.kind
    ? `<div class="dmsrc">on ${esc(src.kind)} at <code>${esc(src.where)}</code>${
        // A mapped path this container does not have. Not a fault: it can be a
        // share the daemon mounts and BuilderBot has no business reading. It is
        // said because nothing else here will ever act on it, and a line of
        // configuration that does nothing should not look like it does.
        (src.strays || []).length
          ? `<br><span class="dim">${esc((src.strays || []).join(", "))} ${
              src.strays.length > 1 ? "are" : "is"} mapped but not mounted here:
              the daemon's own, and nothing on this side checks ${
              src.strays.length > 1 ? "them" : "it"}</span>` : ""}</div>`
    : "";
  // The picker: every node, online or not: an offline node's view is its
  // last-known list in the ghosted state the blind path draws.
  // One tab, re-rendered per pick (docs/nodes.md §13), never a tab per node.
  const dnodes = (nodesList || []).filter(n => n.kind !== "local");
  if (nodesList === null) loadNodes();
  const picker = dnodes.length > 1 || (dnodes.length === 1 && dockerNode
                                       && dnodes[0].id !== dockerNode)
    ? `<div class="field histbar dmpick"><label for="dmNode">Node</label>
        <select id="dmNode" aria-label="node">${dnodes.map(n =>
          `<option value="${esc(n.id)}"${n.id === dockerNode ? " selected" : ""}>${
            esc(n.name)}: ${esc(n.state)}</option>`).join("")}</select></div>`
    : "";
  // What a session is waiting on, above everything else: somebody is blocked
  // on these, and this is the tab whose dial sent them here. The bell carries
  // them too, the way root asks sit on the Nodes tab and in the bell.
  const asks = (typeof ph !== "undefined" && ph?.asks || [])
    .filter(a => a.kind === "rebuild");
  const askRows = asks.map(a => `<div class="row dmask">
      <div class="grow"><div class="name">rebuild: ${esc(a.why)}</div>
        <div class="phcmd">bb ${esc(a.cmd.join(" "))}</div>
        <div class="sub">${esc(a.asker ? a.asker + "'s session in " + (a.project || "a project")
                                       : a.project || "a session")} asks to rebuild it · ${
          a.left > 60 ? `${Math.floor(a.left / 60)} min left to answer`
                      : `${a.left}s left to answer`}</div></div>
      <span class="acts">
        <button type="button" data-rdeny="${a.id}">Deny</button>
        <button type="button" class="primary" data-rallow="${a.id}">Allow</button>
      </span></div>`).join("");
  // `dmstale` while the rows are the last answer and a new one is on its
  // way: what a reader waiting on a refresh looks at, and what the note
  // below says in words.
  el.innerHTML = `<div class="dmtab${dockerFetching ? " dmstale" : ""}">${picker}${askRows}${note
      ? `<div class="empty">${esc(note)}</div>` : srcLine}${
    // Blind, the list is what is on record here rather than what is on the
    // daemon, and "nothing on this daemon yet" would be a claim about a
    // machine nobody just asked.
    rows || `<div class="empty">${blind
      ? "nothing on record here: an instance appears once it has been sent"
      : "nothing on this daemon yet"}</div>`}
    <div class="actbar macros">${mayDocker()
        ? `<button id="bDockerNew">New container</button>` : ""
      }<button id="bDockerRe">Refresh</button>${
      dockerFetching ? `<span class="dim dmfresh">refreshing…</span>` : ""}</div></div>`;
  gateDocker(el, off);
  // Every tail sits at its own bottom after a draw. The list repaints only
  // when the job moved, so between draws the reader keeps whatever scroll
  // they chose; what this stops is a redraw putting them back at the top of
  // output whose point is at the end.
  el.querySelectorAll('.dmlog[data-tail="1"]').forEach(t => {
    t.scrollTop = t.scrollHeight;
  });
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
