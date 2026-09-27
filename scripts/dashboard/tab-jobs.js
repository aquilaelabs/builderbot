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

function openJobsTab(){
  // The kind's open hook loads; a second load here asked the queue twice
  // for one press (the quiet-page invariant in uniform.mjs holds it now).
  openTab({kind: "jobs", arg: "__jobs", label: "Jobs"});
}

async function loadJobs(){
  try{
    const j = await (await fetch(`/api/v1/jobs?n=100${jobsActive ? "&active=1" : ""}`)).json();
    jobsErr = j.error || "";
    jobsList = j.jobs || [];
    jobsNodes = j.nodes || {};
    // An unfolded log follows its job: refetched with the list, so a running
    // job's tail moves on the same revision that moves its row.
    await Promise.all([...jobsOpen].map(async id => {
      const r = await (await fetch(`/api/v1/jobs?id=${encodeURIComponent(id)}`)).json();
      if (!r.error) jobsLogs[id] = r.log || "";
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
    return `${esc(s.action || "compose")} ${esc(j.project || "")}${
      s.instance && s.instance !== "main" ? "/" + esc(s.instance) : ""}`;
  if (j.type === "self-update") return "agent self-update";
  if (j.type === "system") return `apply ${esc(s.apply || "config")} on the node`;
  if (j.type === "toolchain") return `${esc(s.action || "install")} ${esc((s.names || []).join(", "))}`;
  if (j.type === "image") return `${esc(s.action || "add")} image ${esc(s.image || "")}`;
  if (j.type === "cache-clear") return `clear ${s.project ? esc(s.project) + "'s caches" : "every cache"}`;
  // Run on another node of the project's set because its primary was not
  // up (R82 step 6): said on the row, since the row is where it is looked for.
  const stood = s.fell_over ? " (its primary was not up)" : "";
  const argv = (Array.isArray(s.argv) ? s.argv.join(" ") : "") + stood;
  // A job with a source is a build of that project's tree, and says so
  // before the command (docs/nodes.md §6).
  const src = j.source?.digest ? `${esc(j.project || s.project || "")} · ` : "";
  return `${src}exec ${esc(argv.slice(0, 80))}${argv.length > 80 ? "…" : ""}`;
}

function jobStatePill(j){
  const cls = {succeeded: "ok", failed: "bad", running: "note",
               assigned: "note", canceled: "warn"}[j.state] || "";
  const word = j.state === "running" && j.cancel ? "stopping"
             : j.state === "running" && j.step ? j.step : j.state;
  return `<span class="pill ${cls} jbstate">${esc(word)}</span>`;
}

// Where and when: the node by name, and the timings that are known: a
// queued job has only its wait so far, a finished one how long it took.
function jobWhen(j){
  const node = jobsNodes[j.node] || (j.node ? j.node : "any node that fits");
  const bits = [`on ${esc(node)}`];
  if (j.state === "queued") bits.push(`queued ${ago(j.queued)}`);
  else if (j.started && !j.ended) bits.push(`started ${ago(j.started)}`);
  else if (j.started && j.ended)
    bits.push(`${ago(j.queued)}`, `took ${Math.max(1, j.ended - j.started)}s`);
  else if (j.ended) bits.push(`${ago(j.ended)}`);
  if (j.exit_code !== null && j.exit_code !== undefined && j.exit_code !== 0)
    bits.push(`exit ${j.exit_code}`);
  return bits.join(" · ");
}

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
    d.list.innerHTML = `<div class="loading">loading…</div>`;
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
    <div class="row stack2 jbrow" data-job="${esc(j.id)}" data-state="${esc(j.state)}">
      <div class="grow">
        <div class="name">${jobTitle(j)} ${jobStatePill(j)}
          <span class="dim">· ${esc(j.type)}</span></div>
        <div class="sub">${jobWhen(j)}${j.requested_by && j.requested_by !== "operator"
          ? ` · asked by ${esc(j.requested_by)}` : ""}</div>
        ${j.error ? `<div class="sub jberr warn">${esc(j.error)}</div>` : ""}
        ${jobOutputs(j)}
        ${open ? `<pre class="dmlog jblog" data-tail="1">${
            // "yet" only while there could be more. A job that has ENDED
            // with an empty log is not waiting for anything, and saying it
            // is sends somebody back to look again at nothing.
            esc((jobsLogs[j.id] || "").slice(-4000)
                || (over ? "(this job wrote nothing)" : "(no output yet)"))}</pre>` : ""}
      </div>
      <div class="actbar">
        <button type="button" data-jb="log" title="${open ? "fold the log away" : "what it wrote, the last 4000 characters"}">${
          open ? "Hide log" : "Log"}</button>
        ${over || j.cancel ? "" : `<button type="button" class="danger" data-jb="cancel"
          title="${j.state === "queued" ? "take it off the queue before it starts"
                   : "stop it where it is: the row moves when the runner reports that it did"}">Cancel</button>`}
      </div>
    </div>`;
  }).join("");
  d.list.innerHTML = rows + (!jobsList.length
    ? `<div class="empty">${jobsActive ? "nothing is running or waiting"
                                       : "no jobs yet: a compose action, an exec on a node, or an agent update will appear here"}</div>` : "");
  // Paged like every other long list here. This one grows without bound:
  // every compose action, exec and agent update lands on it forever, so it
  // was the tab most in need of it and the one that had it least.
  paginate(d.list, ":scope > .jbrow", {key: "jbList", noun: "jobs"});
  d.setFoot(`Cancel stops a job. Nothing here edits one.`);
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
