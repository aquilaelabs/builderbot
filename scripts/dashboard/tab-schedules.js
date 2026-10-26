// The Schedules page (R117): an administrator's own cron, as Unraid's User
// Scripts are. Each schedule a row: its name, whether it is on, its
// timetable said in words, the node it runs on and as whom, its last run
// (its state, when, and its log on the Jobs page) and its next; Run now,
// Edit, Turn on or off, and Remove behind its More. New schedule in the
// bar opens the same dialog a row's Edit does. The static analysis scan is
// built in: off until turned on, which asks for its node and its paths.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/schedules, read when the page opens, after every press and on the
// jobs revision, since a run is a job.

"use strict";

let schedData = null;            // the last answer, or null before the first
let schedErr = "";
let schedRev = 0;
let schedDraft = {};             // what the open dialog holds

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
  const where = !s.node ? "nowhere picked yet" : !n ? "on a node no longer enrolled"
    : n.controller ? "on the controller" : `on ${n.name}${s.as === "root" ? " as root" : ""}`;
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
    </div>`;
}

// When a schedule runs, as User Scripts says it: a pick of the usual ones,
// and cron's five fields under Custom for anything else.
const SCHED_WHEN = [["0 * * * *", "Hourly"], ["0 4 * * *", "Daily, at 4:00"], ["0 4 * * 0", "Weekly, Sundays at 4:00"],
                    ["0 4 1 * *", "Monthly, on the 1st at 4:00"]];

// The dialog a schedule is added or changed with (the a-dialog layout, the
// operator, 26 Oct: as few fields as User Scripts): its name, when, where it
// runs, and its script; the scan's paths in place of a script. A run is
// stopped after a day, which is not asked.
function schedForm(s){
  const v = k => esc(String(schedDraft[k] ?? s?.[k] ?? ""));
  const nodes = (schedData.nodes || []);
  const scan = s?.builtin === "scan";
  const env = {...(s?.env || {}), ...(schedDraft.env || {})};
  const cron = schedDraft.cron ?? s?.cron ?? SCHED_WHEN[1][0];
  const custom = schedDraft.custom ?? !SCHED_WHEN.some(([c]) => c === cron);
  const envField = (k, label, hint) => `<div class="field">${lbl("schEnv" + k, label)}
      <input id="schEnv${k}" data-schedenv="${k}" type="text" value="${esc(env[k] || "")}" spellcheck="false" autocomplete="off">
      <div class="hint">${esc(hint)}</div></div>`;
  return `<div data-schedform="${esc(s?.id || "new")}">
      ${scan ? "" : `<div class="field">${lbl("schName", "Name")}
        <input id="schName" data-schedf="name" type="text" value="${v("name")}" autocomplete="off"></div>`}
      <div class="prefrow ctlrow">
        <div class="setrow col ctlrow">${lbl("schWhen", "When")}
          <select id="schWhen">${optionList([...SCHED_WHEN, ["", "Custom"]], custom ? "" : cron)}</select></div>
        <div class="setrow col ctlrow">${lbl("schNode", "Runs on")}
          <select id="schNode" data-schedf="node">${s?.node || schedDraft.node ? "" : `<option value="">pick where</option>`}${
            optionList(nodes.map(n => [n.id, n.name]), schedDraft.node ?? s?.node)}</select></div>
      </div>
      <div class="field" id="schCronF"${custom ? "" : " hidden"}>${lbl("schCron", "Timetable", "cron's five fields: minute, hour, day of the month, month, weekday")}
        <input id="schCron" data-schedf="cron" type="text" value="${esc(cron)}" spellcheck="false" autocomplete="off"
          placeholder="0 4 * * 0">
        <div class="hint" id="schCronSaid">${esc(s?.words || "0 4 * * 0 is Sundays at 4:00")}</div></div>
      <div class="field" id="schAsRow">${schedAs(s)}</div>
      ${scan ? envField("SCANNER_SOURCE_PATH", "Where the projects are on that node", "the share BuilderBot's /workspace is, as that node mounts it")
        + envField("SCANNER_REPORTS_PATH", "The reports folder", "the folder the controller reads at /reports, as that node mounts it")
        + envField("SCANNER_CACHE_PATH", "The scanners' cache", "kept between runs; the reports folder's parent when left empty")
        : `<div class="field">${lbl("schScript", "Script")}
        <textarea id="schScript" data-schedf="script" rows="8" spellcheck="false">${v("script")}</textarea>
        <div class="hint">Run by bash where it runs: on the controller, as the controller's account, with all it holds; on a node, as its jobs account. Its output is the job's log on the Jobs page.</div></div>`}
    </div>`;
}

// As whom it runs on a node BuilderBot provisioned as a sandbox, the one
// place root is BuilderBot's to use (as bb root run's): asked only there.
// Anywhere else it is the jobs account, with nothing to ask (the operator,
// 26 Oct), and a schedule saved as root elsewhere says why it will not run.
function schedAs(s){
  const nid = schedDraft.node ?? s?.node ?? "", n = (schedData.nodes || []).find(x => x.id === nid);
  const as = schedDraft.as ?? s?.as ?? "job";
  if (n?.sandbox) return `${lbl("schAs", "Runs as")}
    <select id="schAs" data-schedf="as">${optionList([["job", "the node's jobs account"], ["root", "root"]], as)}</select>`;
  return s?.as === "root" && n ? `<div class="hint warn">Saved to run as root, which ${esc(n.name)} does not allow: it is not a BuilderBot sandbox. Saved again, it runs as the jobs account.</div>` : "";
}

// Open the dialog on a schedule, or on a new one.
function openSchedForm(s){
  let m = document.getElementById("schedmodal");
  if (!m){
    m = document.createElement("div");
    m.id = "schedmodal"; m.className = "modal"; m.hidden = true;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true"); m.setAttribute("aria-labelledby", "schT");
    document.body.appendChild(m);
    armModal(m);
  }
  // A new one runs on the controller, daily, unless picked otherwise.
  schedDraft = s ? {} : {as: "job", node: (schedData.nodes || []).find(n => n.controller)?.id || "", cron: SCHED_WHEN[1][0]};
  // One saved as root where root is not BuilderBot's is saved as the jobs
  // account: the note under Runs on says so.
  const at = (schedData.nodes || []).find(n => n.id === s?.node);
  if (s?.as === "root" && at && !at.sandbox) schedDraft.as = "job";
  m.innerHTML = `<div class="box"><h3 id="schT">${s ? esc(s.name || "Schedule") : "New schedule"}</h3>
    ${schedForm(s)}
    ${dlgFoot(`<button type="button" data-schedcancel>Cancel</button>`,
              `<button type="button" class="primary" data-schedsave="${esc(s?.id || "")}">${s ? "Save" : "Add"}</button>`,
              `<span class="state" id="schSay"></span>`)}</div>`;
  wireSchedForm(m, s);
  m.hidden = false;
  m.onclick = e => { if (e.target === m) closeSchedForm(); };
}

function closeSchedForm(){
  const m = document.getElementById("schedmodal");
  schedDraft = {};
  if (m) m.hidden = true;
}

function wireSchedForm(m, s){
  m.querySelector("[data-schedcancel]").onclick = closeSchedForm;
  // The timetable says what it means as it is typed, and Runs as follows
  // the node picked.
  const wireField = f => f.oninput = f.onchange = () => {
    schedDraft[f.dataset.schedf] = f.value;
    if (f.dataset.schedf === "cron"){
      const said = m.querySelector("#schCronSaid");
      if (said) said.textContent = f.value.trim().split(/\s+/).length === 5 ? "said in words once saved" : "cron's five fields: minute hour day month weekday";
    }
    if (f.dataset.schedf === "node"){
      const row = m.querySelector("#schAsRow"), n = (schedData.nodes || []).find(x => x.id === f.value);
      // Off a sandbox, the jobs account: root is not this node's to give.
      if (!n?.sandbox && (schedDraft.as ?? s?.as) === "root") schedDraft.as = "job";
      row.innerHTML = schedAs(s);
      const as = row.querySelector("[data-schedf]");
      if (as) wireField(as);
    }
  };
  m.querySelectorAll("[data-schedf]").forEach(wireField);
  // A pick of When is its cron; Custom shows the five fields to type.
  const when = m.querySelector("#schWhen"), cronF = m.querySelector("#schCronF");
  when.onchange = () => {
    schedDraft.custom = !when.value;
    if (when.value){ schedDraft.cron = when.value; m.querySelector("#schCron").value = when.value; }
    cronF.hidden = !!when.value;
    if (!when.value) m.querySelector("#schCron").focus();
  };
  m.querySelectorAll("[data-schedenv]").forEach(f => f.oninput = () => {
    schedDraft.env = {...(schedDraft.env || {}), [f.dataset.schedenv]: f.value};
  });
  m.querySelector("[data-schedsave]").onclick = async e => {
    const b = e.currentTarget, id = b.dataset.schedsave, body = {action: "save", ...(id ? {id} : {})};
    for (const k of ["name", "cron", "node", "as", "script"]) if (k in schedDraft) body[k] = schedDraft[k];
    if (schedDraft.env) body.env = schedDraft.env;
    busy(b, id ? "Saving" : "Adding");
    const j = await postSchedule(body);
    unbusy(b, id ? "Save" : "Add");
    if (j.error){ const say = m.querySelector("#schSay"); if (say) say.textContent = j.error; return; }
    closeSchedForm();
    notify(`${j.schedule?.name || "the schedule"} saved: ${j.schedule?.on ? j.schedule.words : "off"}`);
    loadSchedules();
  };
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
  d.setBar(`<span class="sp"></span>${may ? `<span class="actbar"><button type="button" class="primary" id="bSchedNew">New schedule</button></span>` : ""}`);
  d.list.innerHTML = pageHead({facts: [["Schedules", String(rows.length)], ["Turned on", String(on.length)],
                                       ["Next run", next ? `${next.name}, ${schedWhen(next.next_at)}` : "none"]]})
    + docSection("schedules", "list", "Schedules", `${rows.length}`,
        `<div class="schedrows">${rows.map(s => schedRow(s, may)).join("")}</div>`);
  wireSchedules(d.el);
}

function wireSchedules(root){
  wireSections(root);
  const nb = root.querySelector("#bSchedNew");
  if (nb) nb.onclick = () => openSchedForm(null);
  root.querySelectorAll("[data-schededit]").forEach(b => b.onclick = () =>
    openSchedForm((schedData.schedules || []).find(x => x.id === b.dataset.schededit)));
  root.querySelectorAll("[data-schedon]").forEach(b => b.onclick = async () => {
    const turning = b.dataset.on === "1";
    const s = (schedData.schedules || []).find(x => x.id === b.dataset.schedon);
    // Turning on a schedule with no node, or the scan without its paths,
    // opens its form: the server would refuse it, saying what is missing.
    if (turning && (!s?.node || (s?.builtin === "scan" && !(s.env || {}).SCANNER_REPORTS_PATH))){
      openSchedForm(s);
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
