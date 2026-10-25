// The Schedules page (R117): an administrator's own cron, as Unraid's User
// Scripts are. Each schedule a row: its name, whether it is on, its
// timetable said in words, the node it runs on and as whom, its last run
// (its state, when, and its log on the Jobs page) and its next; Run now,
// Edit, Turn on or off, and Remove behind its More. New schedule in the
// bar opens the same form a row's Edit does, at the top of the list. The
// static analysis scan is built in: off until turned on, which asks for its
// node and its paths.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/schedules, read when the page opens, after every press and on the
// jobs revision, since a run is a job.

"use strict";

let schedData = null;            // the last answer, or null before the first
let schedErr = "";
let schedRev = 0;
let schedEdit = "";              // the schedule whose form is open, "new" for a new one, "" for none
let schedDraft = {};             // what the open form holds, kept across redraws

function openSchedulesTab(){
  openTab({kind: "schedules", arg: "__schedules", label: "Schedules"});
}

async function loadSchedules(){
  try{
    const j = await (await bootFetch("/api/schedules")).json();
    schedErr = j.error || "";
    schedData = j.error ? {schedules: [], nodes: [], may: false} : j;
  }catch(e){
    schedErr = failWords(e);
    schedData = schedData || {schedules: [], nodes: [], may: false};
  }
  schedRev++;
  if (tabs.some(t => t.kind === "schedules")) drawPanes();
}

async function postSchedule(body){
  try{
    const j = await (await postJSON("/api/schedules", body)).json();
    if (j.error) notify(j.error, true);
    return j;
  }catch(e){
    notify("schedules: " + failWords(e), true);
    return {error: String(e)};
  }
}

// When a run was or will be, as a person reads it: a weekday and a time,
// the date where it is not this week.
function schedWhen(s){
  if (!s) return "";
  const d = new Date(s * 1000), soon = Math.abs(d - Date.now()) < 6 * 86400000;
  return d.toLocaleString(undefined, soon ? {weekday: "short", hour: "numeric", minute: "2-digit"}
                                          : {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
}

const SCHED_STATE = {succeeded: ["ok", "succeeded"], failed: ["bad", "failed"], canceled: ["warn", "canceled"],
                     running: ["live", "running"], queued: ["", "waiting"], assigned: ["", "waiting"]};

function schedRow(s, may){
  const n = (schedData.nodes || []).find(x => x.id === s.node);
  const last = s.last || {}, st = SCHED_STATE[last.state] || ["", last.state || ""];
  const where = s.node ? `on ${n ? n.name : "a node no longer enrolled"} as ${s.as === "root" ? "root" : "its jobs account"}`
    : "no node picked yet";
  const lastSaid = last.error ? `<span class="pill bad">not run</span> ${esc(last.error)}`
    : last.job ? `<span class="pill ${st[0]}">${esc(st[1])}</span> ${esc(ago(last.at))}${last.late ? `, late: it was due ${esc(last.late)}` : ""}
        <a href="#" data-schedlog="${esc(last.job)}">its log</a>` : "never run";
  const acts = !may ? "" : `<span class="actbar">
      <button type="button" data-schedrun="${esc(s.id)}"${s.node ? "" : " disabled"} title="${s.node ? "run it now, once" : "pick its node first"}">Run now</button>
      <button type="button" data-schededit="${esc(s.id)}">Edit</button>
      <button type="button" data-schedon="${esc(s.id)}" data-on="${s.on ? "0" : "1"}">${s.on ? "Turn off" : "Turn on"}</button>
      ${s.builtin ? "" : actMore([`<button type="button" class="danger" data-schedrm="${esc(s.id)}">Remove</button>`], true)}</span>`;
  return `<div class="row schedrow" data-sched="${esc(s.id)}">
      <div class="grow">
        <div class="top"><b>${esc(s.name || "")}</b> <span class="pill${s.on ? " ok" : ""}">${s.on ? "on" : "off"}</span>${
          s.builtin ? ` <span class="pill">built in</span>` : ""}</div>
        ${factGrid([["When", s.words || ""], ["Where", where], ["Last run", lastSaid, {html: true}],
                    ["Next run", s.on && s.next_at ? schedWhen(s.next_at) : ""]], "schedfacts")}
      </div>${acts}
    </div>${schedEdit === s.id ? schedForm(s) : ""}`;
}

// The form a schedule is added or changed with: its name, its timetable
// with what it says in words beside it, its node and as whom, its timeout,
// and its script; the scan's paths in place of a script.
function schedForm(s){
  const v = k => esc(String(schedDraft[k] ?? s?.[k] ?? ""));
  const nodes = (schedData.nodes || []);
  const as = schedDraft.as ?? s?.as ?? "job";
  const scan = s?.builtin === "scan";
  const env = {...(s?.env || {}), ...(schedDraft.env || {})};
  const envField = (k, label, hint) => `<div class="setrow col ctlrow"><label class="lbl" for="schEnv${k}">${esc(label)}</label>
      <input id="schEnv${k}" data-schedenv="${k}" type="text" value="${esc(env[k] || "")}" spellcheck="false" autocomplete="off">
      <div class="hint">${esc(hint)}</div></div>`;
  return `<div class="field schedform" data-schedform="${esc(s?.id || "new")}">
      ${scan ? "" : `<div class="setrow col ctlrow"><label class="lbl" for="schName">Name</label>
        <input id="schName" data-schedf="name" type="text" value="${v("name")}" autocomplete="off"></div>`}
      <div class="setrow col ctlrow"><label class="lbl" for="schCron">Timetable</label>
        <input id="schCron" data-schedf="cron" type="text" value="${v("cron")}" spellcheck="false" autocomplete="off"
          placeholder="minute hour day month weekday: 0 4 * * 0">
        <div class="hint" id="schCronSaid">${esc(s?.words || "cron's five fields: 0 4 * * 0 is Sundays at 4:00")}</div></div>
      <div class="setrow col ctlrow"><label class="lbl" for="schNode">Node</label>
        <select id="schNode" data-schedf="node"><option value="">pick a node</option>${nodes.map(n =>
          `<option value="${esc(n.id)}"${(schedDraft.node ?? s?.node) === n.id ? " selected" : ""}>${esc(n.name)}</option>`).join("")}</select></div>
      <div class="setrow col ctlrow"><label class="lbl" for="schAs">Runs as</label>
        <select id="schAs" data-schedf="as"><option value="job"${as === "job" ? " selected" : ""}>the node's jobs account</option>
          <option value="root"${as === "root" ? " selected" : ""}>root (a sandbox node)</option></select></div>
      <div class="setrow col ctlrow"><label class="lbl" for="schTimeout">Stopped after (minutes)</label>
        <input id="schTimeout" data-schedf="timeout_m" type="number" min="1" max="1440" value="${
          esc(String(schedDraft.timeout_m ?? Math.round((s?.timeout || 3600) / 60)))}"></div>
      ${scan ? envField("SCANNER_SOURCE_PATH", "Where the projects are on that node", "the share BuilderBot's /workspace is, as that node mounts it")
        + envField("SCANNER_REPORTS_PATH", "The reports folder", "the folder the controller reads at /reports, as that node mounts it")
        + envField("SCANNER_CACHE_PATH", "The scanners' cache", "kept between runs; the reports folder's parent when left empty")
        : `<div class="setrow col ctlrow"><label class="lbl" for="schScript">Script</label>
        <textarea id="schScript" data-schedf="script" rows="8" spellcheck="false">${v("script")}</textarea>
        <div class="hint">Run by bash on the node. Its output is the job's log on the Jobs page.</div></div>`}
      <div class="actbar"><span class="state" id="schSay"></span><span class="sp"></span>
        <button type="button" data-schedcancel>Cancel</button>
        <button type="button" class="primary" data-schedsave="${esc(s?.id || "")}">${s ? "Save" : "Add"}</button></div>
    </div>`;
}

function renderSchedulesInto(i){
  const d = docSurface(i, "schedules");
  if (!d) return;
  if (schedData === null){
    d.setBar(`<span class="sp"></span><span class="actbar"><button type="button" class="primary" disabled>New schedule</button></span>`);
    d.list.innerHTML = skTpl(pageHead({facts: [["Schedules", GHOST], ["Turned on", GHOST], ["Next run", GHOST]]})
      + docSection("schedules", "list", "Schedules", "", skRows(2)));
    loadSchedules();
    return;
  }
  if (schedErr){
    d.setBar("");
    d.list.innerHTML = `<div class="field"><div class="notice bad">${esc(schedErr)}</div></div>`;
    return;
  }
  const rows = schedData.schedules || [], may = !!schedData.may;
  const on = rows.filter(s => s.on), next = on.filter(s => s.next_at).sort((a, b) => a.next_at - b.next_at)[0];
  d.setBar(`<span class="sp"></span>${may ? `<span class="actbar"><button type="button" class="primary" id="bSchedNew"${
    schedEdit === "new" ? " disabled" : ""}>New schedule</button></span>` : ""}`);
  d.list.innerHTML = pageHead({facts: [["Schedules", String(rows.length)], ["Turned on", String(on.length)],
                                       ["Next run", next ? `${next.name}, ${schedWhen(next.next_at)}` : "none"]]})
    + docSection("schedules", "list", "Schedules", `${rows.length}`,
        (schedEdit === "new" ? schedForm(null) : "")
        + `<div class="schedrows">${rows.map(s => schedRow(s, may)).join("")}</div>`);
  wireSchedules(d.el);
}

function wireSchedules(root){
  wireSections(root);
  const redraw = () => { schedRev++; drawPanes(); };
  const nb = root.querySelector("#bSchedNew");
  if (nb) nb.onclick = () => { schedEdit = "new"; schedDraft = {as: "job", timeout_m: 60}; redraw(); };
  root.querySelectorAll("[data-schededit]").forEach(b => b.onclick = () => {
    schedEdit = schedEdit === b.dataset.schededit ? "" : b.dataset.schededit; schedDraft = {}; redraw();
  });
  root.querySelectorAll("[data-schedcancel]").forEach(b => b.onclick = () => { schedEdit = ""; schedDraft = {}; redraw(); });
  // What is typed is kept across a redraw (the poll draws the page again),
  // and the timetable says what it means as it is typed.
  root.querySelectorAll("[data-schedf]").forEach(f => f.oninput = f.onchange = () => {
    schedDraft[f.dataset.schedf] = f.value;
    if (f.dataset.schedf === "cron"){
      const said = root.querySelector("#schCronSaid");
      if (said) said.textContent = f.value.trim().split(/\s+/).length === 5 ? "said in words once saved" : "cron's five fields: minute hour day month weekday";
    }
  });
  root.querySelectorAll("[data-schedenv]").forEach(f => f.oninput = () => {
    schedDraft.env = {...(schedDraft.env || {}), [f.dataset.schedenv]: f.value};
  });
  root.querySelectorAll("[data-schedsave]").forEach(b => b.onclick = async () => {
    const id = b.dataset.schedsave, body = {action: "save", ...(id ? {id} : {})};
    for (const k of ["name", "cron", "node", "as", "script"]) if (k in schedDraft) body[k] = schedDraft[k];
    if ("timeout_m" in schedDraft) body.timeout = Math.round(Number(schedDraft.timeout_m) * 60);
    if (schedDraft.env) body.env = schedDraft.env;
    busy(b, id ? "Saving" : "Adding");
    const j = await postSchedule(body);
    unbusy(b, id ? "Save" : "Add");
    if (j.error){ const say = root.querySelector("#schSay"); if (say) say.textContent = j.error; return; }
    schedEdit = ""; schedDraft = {};
    notify(`${j.schedule?.name || "the schedule"} saved: ${j.schedule?.on ? j.schedule.words : "off"}`);
    loadSchedules();
  });
  root.querySelectorAll("[data-schedon]").forEach(b => b.onclick = async () => {
    const turning = b.dataset.on === "1";
    const s = (schedData.schedules || []).find(x => x.id === b.dataset.schedon);
    // Turning on a schedule with no node, or the scan without its paths,
    // opens its form: the server would refuse it, saying what is missing.
    if (turning && (!s?.node || (s?.builtin === "scan" && !(s.env || {}).SCANNER_REPORTS_PATH))){
      schedEdit = s.id; schedDraft = {}; redraw();
      return notify(s?.builtin === "scan" ? "the scan needs its node and paths before it is turned on" : "pick its node first");
    }
    busy(b, turning ? "Turning on" : "Turning off");
    await postSchedule({action: "save", id: b.dataset.schedon, on: turning});
    loadSchedules();
  });
  root.querySelectorAll("[data-schedrun]").forEach(b => b.onclick = async () => {
    const s = (schedData.schedules || []).find(x => x.id === b.dataset.schedrun);
    if (!await askYes(`Run ${s?.name || "this schedule"} now?\n\nIt runs once on its node, as a job, whatever its timetable says.`)) return;
    busy(b, "Running");
    const j = await postSchedule({action: "run", id: b.dataset.schedrun});
    unbusy(b, "Run now");
    if (j.job) notify(`${s?.name || "the schedule"} is running: its log is on the Jobs page`);
    loadSchedules();
  });
  root.querySelectorAll("[data-schedrm]").forEach(b => b.onclick = async () => {
    const s = (schedData.schedules || []).find(x => x.id === b.dataset.schedrm);
    if (!await askYes(`Remove ${s?.name || "this schedule"}?\n\nIts script goes with it; the logs of its runs stay on the Jobs page.`)) return;
    await postSchedule({action: "remove", id: b.dataset.schedrm});
    loadSchedules();
  });
  root.querySelectorAll("[data-schedlog]").forEach(a => a.onclick = e => { e.preventDefault(); openJob(a.dataset.schedlog); });
}
