// The Jobs tab: the queue, readable and stoppable. Phase 4 of docs/nodes.md
//: every job the controller has taken (an exec on a node, a compose action
// on a dev instance, an agent self-update), where it was placed, what it is
// doing now, how it ended, and its log. Its own classic script beside
// index.html, per the new-surface rule (§13): same page, same global scope,
// one file per surface.
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs;
// this file only fills slots. Data comes from /api/v1/jobs, fetched when the
// "jobs" revision token moves, never from the status poll. The one verb is
// Cancel; a job is never edited, and a finished one is history (door 1).

"use strict";

let jobsList = null;             // last answer, or null before the first
let jobsNodes = {};              // id -> name, from the same answer
let jobsRev = 0;                 // bumped when it changes, so panes repaint
let jobsErr = "";
let jobsActive = false;          // the filter: everything, or only what is not over
const jobsOpen = new Set();      // ids whose log is unfolded
const jobsLogs = {};             // id -> the log fetched for an unfolded row
let jobsFocus = "";              // a row to bring into view on the next draw (openJob)
let jobsMarked = "";             // ...and to mark, across redraws, until another is opened

function openJobsTab(){
  // The kind's open hook loads; a second load here asked the queue twice
  // for one press (the quiet-page invariant in uniform.mjs holds it now).
  openTab({kind: "jobs", arg: "__jobs", label: "Jobs"});
}

// One job's row, its log open and brought into view: what a row on Home's
// Last jobs opens (R218 step 5).
function openJob(id){
  jobsOpen.add(id);
  jobsFocus = jobsMarked = id;
  openJobsTab();
  loadJobs();
}

async function loadJobs(){
  try{
    const j = await (await bootFetch(`/api/v1/jobs?n=100${jobsActive ? "&active=1" : ""}`)).json();
    jobsErr = j.error || "";
    jobsList = j.jobs || [];
    jobsNodes = j.nodes || {};
    // An unfolded log follows its job: refetched with the list, so a running
    // job's tail moves on the same revision that moves its row.
    await Promise.all([...jobsOpen].map(async id => {
      const r = await (await fetch(`/api/v1/jobs?id=${encodeURIComponent(id)}`)).json();
      // A job answers with its own fields, `error` among them for one that
      // failed; a refused request has no id. Reading a failed job's error
      // as the request's kept its log out, so every failed job read "(this
      // job wrote nothing)" (B658, the operator, 11 Oct).
      if (r.id) jobsLogs[id] = r.log || "";
    }));
  }catch(e){
    jobsErr = String(e);
    jobsList = jobsList || [];
  }
  jobsRev++;
  if (tabs.some(t => t.kind === "jobs")) drawPanes();
}

async function jobAct(body){
  const j = await (await fetch("/api/v1/jobs", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)})).json().catch(() => ({error: "no answer"}));
  if (j.error) notify(j.error, true);
  await loadJobs();
  return j;
}

// What the job is, in the words the operator used to start it: a compose
// job says its action and instance, an exec says its command.
function jobTitle(j){
  const s = j.spec || {};
  if (j.type === "compose")
    return `${esc(s.action || "compose")} ${esc(j.project ? projLabel(j.project) : "")}${
      s.instance && s.instance !== "main" ? "/" + esc(s.instance) : ""}`;
  if (j.type === "self-update") return "agent self-update";
  if (j.type === "system") return `apply ${esc(s.apply || "config")} on the node`;
  if (j.type === "toolchain") return `${esc(s.action || "install")} ${esc((s.names || []).join(", "))}`;
  if (j.type === "image") return (s.images || []).length > 1
    ? `${esc(s.action || "add")} ${s.images.length} images` : `${esc(s.action || "add")} image ${esc(s.image || "")}`;
  // A job its caller named in words (nodes.run_wait's title): a shell line
  // is not what a person reads a job list for (the design pass, 4 Oct).
  if (s.title) return esc(s.title);
  if (j.type === "cache-clear") return `clear ${s.project ? esc(projLabel(s.project)) + "'s caches" : "every cache"}`;
  // Run on another node of the project's set because its primary was not
  // up (R82 step 6): said on the row, since the row is where it is looked for.
  const stood = s.fell_over ? " (its primary was not up)" : "";
  const argv = (Array.isArray(s.argv) ? s.argv.join(" ") : "") + stood;
  // A job with a source is a build of that project's tree, and says so
  // before the command (docs/nodes.md §6).
  const src = j.source?.digest ? `${esc(projLabel(j.project || s.project || ""))} · ` : "";
  return `${src}exec ${esc(argv.slice(0, 80))}${argv.length > 80 ? "…" : ""}`;
}

function jobStatePill(j){
  const cls = {succeeded: "ok", failed: "bad", running: "note",
               assigned: "note", canceled: "warn"}[j.state] || "";
  const word = j.state === "running" && j.cancel ? "stopping"
             : j.state === "running" && j.step ? j.step : j.state;
  // A running job is live, and glows (R218 step 7).
  const live = j.state === "running" || j.state === "assigned" ? " live" : "";
  return `<span class="pill ${cls}${live} jbstate">${esc(word)}</span>`;
}

// Where and when: the node by name, and the timings that are known: a
// queued job has only its wait so far, a finished one how long it took.
// The table's cells (R218 step 8): when it last moved, and how long it ran
// with its exit code when that was not 0.
function jobNode(j){
  return esc(jobsNodes[j.node] || (j.node ? j.node : "any node that fits"));
}
function jobWhen(j){
  if (j.state === "queued") return `queued ${ago(j.queued)}`;
  if (j.started && !j.ended) return `started ${ago(j.started)}`;
  return ago(j.ended || j.queued);
}
function jobTook(j){
  const took = j.started && j.ended ? `${Math.max(1, j.ended - j.started)}s` : "";
  // Said once: a reason that already names the exit code keeps it.
  const code = j.exit_code !== null && j.exit_code !== undefined && j.exit_code !== 0
    && !String(j.error || "").includes(`exit ${j.exit_code}`) ? `exit ${j.exit_code}` : "";
  return [took, code].filter(Boolean).join(" · ");
}
// Who asked: every job has an asker, so it is a column and not a line
// under each row; an account is named without its "user:" prefix.
function jobBy(j){
  const by = j.requested_by || "";
  return esc(by.startsWith("user:") ? by.slice(5) : by);
}
const JOB_COLS = [{label: "Job"}, {label: "State", w: "7.5rem"}, {label: "Kind", w: "7rem"},
                  {label: "Node", w: "minmax(0,.7fr)"}, {label: "By", w: "minmax(0,.5fr)"}, {label: "When", w: "7.5rem"},
                  {label: "Took", w: "5.5rem", num: true}, {act: true, w: "10rem"}];

// What a job left behind: the artifacts it delivered into dist/, as the
// download links the Artifacts tab would offer, and the workspace a failed
// build kept on its node for a look (docs/nodes.md §6).
function jobOutputs(j){
  const outs = Array.isArray(j.outputs) ? j.outputs : [];
  if (!outs.length) return "";
  return `<div class="sub jbouts">${outs.map(o => o.kind === "artifact"
    ? `<a href="/api/artifact?project=${encodeURIComponent(j.project)}&path=${
        encodeURIComponent(o.path)}" download>${esc(o.path)}</a>`
    : o.kind === "workspace" ? `workspace kept at <code>${esc(o.path)}</code>` : "")
    .filter(Boolean).join(" · ")}</div>`;
}

function renderJobsInto(i){
  const d = docSurface(i, "jobs");
  if (!d) return;
  if (jobsList === null){
    // Its template (R218 step 16): the bar's filter and the table's head are
    // the page's own; the count and the rows are on their way.
    d.setBar(`<span class="dim">${skv(4)}</span><span class="sp"></span>
      <label class="jbfilter"><input type="checkbox" id="jbActive" ${jobsActive ? "checked" : ""}>
        only what is running or waiting</label>`);
    d.list.innerHTML = skTpl(skTable(JOB_COLS, 6, "jbtbl"));
    wireJobsTab(d.el);
    loadJobs();
    return;
  }
  if (jobsErr){
    d.list.innerHTML = `<div class="hint bad">${esc(jobsErr)}</div>`;
    return;
  }
  const live = jobsList.filter(j => !["succeeded", "failed", "canceled"].includes(j.state)).length;
  d.setBar(`<span class="dim">${jobsList.length} job${jobsList.length === 1 ? "" : "s"}${
      live ? `, ${live} not finished` : ""}</span>
    <span class="sp"></span>
    <label class="jbfilter"><input type="checkbox" id="jbActive" ${jobsActive ? "checked" : ""}>
      only what is running or waiting</label>`);
  const rows = jobsList.map(j => {
    const open = jobsOpen.has(j.id);
    const over = ["succeeded", "failed", "canceled"].includes(j.state);
    return `
    <div class="row stack2 jbrow${j.id === jobsMarked ? " focus" : ""}" data-job="${esc(j.id)}" data-state="${esc(j.state)}">
      ${tblLine(JOB_COLS, [jobTitle(j), jobStatePill(j), esc(j.type), jobNode(j), jobBy(j), jobWhen(j), jobTook(j),
        `<div class="actbar">
          <button type="button" data-jb="log" title="${open ? "fold the log away" : "what it wrote, the last 4000 characters"}">${
            open ? "Hide log" : "Log"}</button>
          ${over || j.cancel ? "" : `<button type="button" class="danger" data-jb="cancel"
            title="${j.state === "queued" ? "take it off the queue before it starts"
                     : "stop it where it is: the row moves when the runner reports that it did"}">Cancel</button>`}
        </div>`])}
      ${j.error ? `<div class="sub jberr warn">${esc(j.error)}</div>` : ""}
      ${jobOutputs(j)}
      ${open ? `<pre class="dmlog jblog" data-tail="1">${
          // "yet" only while there could be more. A job that has ENDED
          // with an empty log is not waiting for anything, and saying it
          // is sends somebody back to look again at nothing.
          esc((jobsLogs[j.id] || "").slice(-4000)
              || (over ? "(this job wrote nothing)" : "(no output yet)"))}</pre>` : ""}
    </div>`;
  }).join("");
  // The tab at a glance (R216, the tiles rule): of the jobs listed, how
  // many run, wait, failed and finished; a tile for a number that is zero
  // and not news (nothing failed) is left out.
  const count = f => jobsList.filter(f).length;
  const tiles = !jobsList.length ? "" : statTiles([
    {label: "running", value: count(j => j.state === "running"), tone: count(j => j.state === "running") ? "ok" : ""},
    {label: "waiting", value: count(j => ["queued", "assigned"].includes(j.state)),
     omit: !count(j => ["queued", "assigned"].includes(j.state))},
    {label: "failed", value: count(j => j.state === "failed"), tone: count(j => j.state === "failed") ? "bad" : "",
     omit: !count(j => j.state === "failed")},
    {label: "succeeded", value: count(j => j.state === "succeeded"), sub: `of ${jobsList.length} listed`},
  ]);
  d.list.innerHTML = tiles + (jobsList.length ? tblWrap(JOB_COLS, rows, "jbtbl") : "") + (!jobsList.length
    ? `<div class="empty">${jobsActive ? "nothing is running or waiting"
                                       : "no jobs yet: a compose action, an exec on a node, or an agent update will appear here"}</div>` : "");
  // Paged like every other long list here. This one grows without bound:
  // every compose action, exec and agent update lands on it forever, so it
  // was the tab most in need of it and the one that had it least.
  const tbl = d.list.querySelector(".jbtbl");
  if (tbl) paginate(tbl, ":scope > .jbrow", {key: "jbList", noun: "jobs"});
  if (jobsFocus){
    const row = d.list.querySelector(`.jbrow[data-job="${CSS.escape(jobsFocus)}"]`);
    if (row){ row.scrollIntoView({block: "nearest"}); jobsFocus = ""; }
  }
  wireJobsTab(d.el);
}

function wireJobsTab(root){
  const f = root.querySelector("#jbActive");
  if (f) f.onchange = () => { jobsActive = f.checked; jobsList = null; jobsRev++; drawPanes(); loadJobs(); };
  // Every tail sits at its own bottom after a draw: the end is where the
  // reason is, the same rule the manager's compose log keeps.
  root.querySelectorAll('.jblog[data-tail="1"]').forEach(t => { t.scrollTop = t.scrollHeight; });
  root.querySelectorAll(".jbrow").forEach(row => {
    const id = row.dataset.job;
    row.querySelectorAll("[data-jb]").forEach(b => b.onclick = async () => {
      if (b.dataset.jb === "log"){
        if (jobsOpen.has(id)) jobsOpen.delete(id); else jobsOpen.add(id);
        await loadJobs();
        return;
      }
      if (b.dataset.jb === "cancel") await jobAct({action: "cancel", id});
    });
  });
}
