// The Scanners page (R145, the operator, 26 Oct): BuilderBot's own static
// analysis scanners (Semgrep, Trivy, mobsfscan) deployed to each node that
// holds projects and run there on one schedule. Every node at once rather
// than one picked in the bar: the question here is whether every project
// is covered, which one node's view cannot answer. Each node is a section
// with its state (not deployed, deployed with its versions, behind), the
// projects it scans, its last run with its log, and Deploy, Update, Run now
// or Remove; the schedule is a section of its own (off, or a timetable in
// words with Run now on every node); the projects no scanner covers close
// the page, each with why. The SARIF a run sends up lands on the Analysis
// page as a host scanner's report did.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/scanners, read when the page opens, after each press and on the
// jobs revision while a run or a deploy is going.

"use strict";

let scannersData = null;          // {nodes, schedule, latest, uncovered}, or null before the first read
let scannersErr = "";
let scannersRev = 0;
let scannersCustom = null;        // the Custom timetable being typed, or null

function openScannersTab(){
  openTab({kind: "scanners", arg: "__scanners", label: "Scanners"});
}

async function loadScanners(){
  try{
    const j = await (await bootFetch("/api/scanners")).json();
    scannersErr = j.error || "";
    if (!j.error) scannersData = j;
  }catch(e){ scannersErr = "scanners: " + failWords(e); }
  scannersRev++;
  if (tabs.some(t => t.kind === "scanners")) drawPanes();
}

async function scannersAct(body){
  const j = await (await postJSON("/api/scanners", body)).json().catch(() => ({error: "no answer"}));
  if (j.error) notify(j.error, true);
  else if (j.note) notify(j.note, true);
  else if (body.action === "deploy") notify("deploying the scanners: the pull is a job on the Jobs page");
  else if (body.action === "deploy-all") notify(`deploying on ${Object.keys(j.nodes || {}).length} node${Object.keys(j.nodes || {}).length === 1 ? "" : "s"}`);
  else if (body.action === "update") notify("updating the scanners: the pull is a job on the Jobs page");
  else if (body.action === "run"){
    const errs = Object.values(j.nodes || {}).filter(x => x.error).map(x => x.error);
    notify(errs.length ? errs.join("; ") : "scanning: each node's run is a job on the Jobs page", errs.length > 0);
  }
  else if (body.action === "check") notify("the newest versions were read");
  await loadScanners();
  return j;
}

const SCAN_WHEN = [["0 4 * * *", "Daily, at 4:00"], ["0 4 * * 0", "Weekly, Sundays at 4:00"], ["0 4 1 * *", "Monthly, on the 1st at 4:00"]];
const SCAN_NAMES = {semgrep: "Semgrep", trivy: "Trivy", mobsfscan: "mobsfscan"};
const SCAN_STATE = {queued: ["", "queued"], assigned: ["", "starting"], running: ["", "running"], succeeded: ["ok", "done"],
                    failed: ["bad", "failed"], canceled: ["", "stopped"]};

function scannersVersions(v){
  return Object.keys(SCAN_NAMES).map(k => `${SCAN_NAMES[k]} ${v?.[k] || "?"}`).join(", ");
}

function scannersLastRun(n){
  const last = n.last || {};
  if (!last.at) return "never run";
  const st = SCAN_STATE[last.state] || ["", last.state || ""];
  return last.error ? `<span class="pill bad">not run</span> ${esc(last.error)}`
    : `<span class="pill ${st[0]}">${esc(st[1])}</span> ${esc(ago(last.at))}${last.late ? `, ${esc(last.late)}` : ""}${
        last.projects?.length ? ` over ${last.projects.length} project${last.projects.length === 1 ? "" : "s"}` : ""}${
        last.job ? ` <a href="#" data-scanlog="${esc(last.job)}">its log</a>` : ""}`;
}

function scannersNodeSection(n){
  const key = `node-${n.node}`;
  const projects = (n.projects || []).length;
  if (n.host_only) return docSection("scanners", key, n.name, "hosts containers only",
    `<div class="field"><div class="hint">This node hosts containers only and holds no project, so there is nothing here to scan.</div></div>`);
  if (!n.deployed){
    return docSection("scanners", key, n.name, "not deployed",
      `<div class="field"><div class="hint">${projects ? `${projects} project${projects === 1 ? "" : "s"} here ${projects === 1 ? "is" : "are"} not scanned until the scanners are deployed.` : "No project is bound to this node; one bound later is scanned here once the scanners are deployed."}</div></div>
       <div class="field"><div class="actbar"><span class="sp"></span><button type="button" class="primary" data-scandeploy="${esc(n.node)}">Deploy</button></div></div>`);
  }
  const behind = Object.keys(n.behind || {});
  const dep = n.deploy_state && !["succeeded", "failed", "canceled"].includes(n.deploy_state) ? "deploying" : "";
  const status = dep ? "deploying" : behind.length ? "update out" : "deployed";
  const facts = [["Runs", scannersVersions(n.versions)], ["Scans", projects ? (n.projects || []).join(", ") : "nothing yet: no project is bound here"],
                 ["Last run", scannersLastRun(n), {html: true}],
                 ["Reports", Object.keys(n.reports || {}).length ? Object.entries(n.reports).map(([k, r]) => `${SCAN_NAMES[k] || k} ${ago(r.at)}`).join(", ") : "none sent yet"]];
  const news = behind.length ? `${behind.map(k => `${SCAN_NAMES[k] || k} ${n.behind[k]}`).join(", ")} ${behind.length === 1 ? "is" : "are"} out: Update pins ${behind.length === 1 ? "it" : "them"} and pulls.` : "";
  return docSection("scanners", key, n.name, status,
    `${factGrid(facts)}
     ${news ? `<div class="field"><div class="hint warn">${esc(news)}</div></div>` : ""}
     <div class="field"><div class="actbar"><span class="sp"></span>
       <button type="button" data-scanrun="${esc(n.node)}"${projects ? "" : " disabled"}>Run now</button>
       ${behind.length ? `<button type="button" class="primary" data-scanupdate="${esc(n.node)}">Update</button>` : ""}
       <button type="button" class="danger" data-scanremove="${esc(n.node)}">Remove</button></div></div>`,
    {cls: behind.length ? "warn" : ""});
}

function scannersScheduleSection(s, deployed){
  const custom = scannersCustom !== null || !SCAN_WHEN.some(([c]) => c === s.cron);
  const cron = scannersCustom ?? s.cron;
  return docSection("scanners", "schedule", "Schedule", s.on ? s.words : "off",
    `<div class="field"><div class="hint">One timetable for every node's scanners; each run is a job on its node, one at a time there, and a run missed while the controller was down runs once when it is back.</div></div>
     <div class="prefrow ctlrow">
       <div class="setrow col ctlrow">${lbl("scanWhen", "When")}
         <select id="scanWhen">${optionList([...SCAN_WHEN, ["", "Custom"]], custom ? "" : s.cron)}</select></div>
     </div>
     <div class="field" id="scanCronF"${custom ? "" : " hidden"}>${lbl("scanCron", "Timetable", "cron's five fields: minute, hour, day of the month, month, weekday")}
       <input id="scanCron" type="text" value="${esc(cron)}" spellcheck="false" autocomplete="off" placeholder="0 4 * * 0"></div>
     ${s.last?.at ? `<div class="field"><div class="sub">Last run ${esc(ago(s.last.at))}${s.last.by ? `, by ${esc(s.last.by)}` : ""}.</div></div>` : ""}
     <div class="field"><div class="actbar"><span class="state">${s.on && s.next_at ? `next ${esc(fmtTime(s.next_at * 1000, {weekday: "short", hour: "numeric", minute: "2-digit"}))}` : ""}</span><span class="sp"></span>
       <button type="button" data-scanrunall${deployed ? "" : " disabled"}>Run now on every node</button>
       <button type="button" data-scansave${custom ? "" : " hidden"}>Save timetable</button>
       <button type="button" class="${s.on ? "" : "primary"}" data-scanon="${s.on ? "0" : "1"}">${s.on ? "Turn off" : "Turn on"}</button></div></div>`);
}

function scannersUncovered(rows){
  if (!rows.length) return docSection("scanners", "uncovered", "Not covered", "every project is", `<div class="field"><div class="sub">Every project is scanned on its node.</div></div>`);
  const cols = [{label: "Project"}, {label: "Why"}];
  return docSection("scanners", "uncovered", "Not covered", String(rows.length),
    tblWrap(cols, rows.map(r => `<div class="row">${tblLine(cols, [esc(r.project), esc(r.why)])}</div>`).join(""), "scanuncovered"));
}

function scannersBar(d){
  const undeployed = d ? (d.nodes || []).filter(n => !n.deployed && !n.host_only && (n.projects || []).length).length : 0;
  return `<span class="sp"></span><span class="actbar"><button type="button" data-scancheck${d ? "" : " disabled"}>Check for updates</button>${
    undeployed ? `<button type="button" class="primary" data-scandeployall>Deploy on ${undeployed === 1 ? "the node" : `${undeployed} nodes`}</button>` : ""}</span>`;
}

function renderScannersInto(i){
  const d = docSurface(i, "scanners");
  if (!d) return;
  if (scannersData === null){
    d.setBar(scannersBar(null));
    d.list.innerHTML = scannersErr ? `<div class="hint bad">${esc(scannersErr)}</div>`
      : skTpl(pageHead({facts: [["Newest known", GHOST], ["Checked", GHOST]]})
        + docSection("scanners", "schedule", "Schedule", "", `<div class="field">${skRows(2)}</div>`)
        + docSection("scanners", "node-", GHOST, "", `<div class="field">${skRows(3)}</div>`)
        + docSection("scanners", "uncovered", "Not covered", "", `<div class="field">${skRows(1)}</div>`));
    if (!scannersErr) loadScanners();
    return;
  }
  const data = scannersData;
  const lt = data.latest || {};
  d.setBar(scannersBar(data));
  const deployed = (data.nodes || []).some(n => n.deployed);
  d.list.innerHTML = pageHead({facts: [["Newest known", scannersVersions(lt.versions)],
      ["Checked", lt.at ? ago(lt.at) : "never: the defaults this release pins"], ["Nodes scanning", String((data.nodes || []).filter(n => n.deployed).length)]]})
    + (lt.error ? `<div class="hint warn">${esc(lt.error)}</div>` : "")
    + scannersScheduleSection(data.schedule || {}, deployed)
    + (data.nodes || []).map(scannersNodeSection).join("")
    + ((data.nodes || []).length ? "" : noNodeYet("the scanners run on a node"))
    + scannersUncovered(data.uncovered || []);
  wireScannersTab(d.el);
}

function wireScannersTab(root){
  wireSections(root);
  const act = (sel, fn) => root.querySelectorAll(sel).forEach(b => b.onclick = async () => { busy(b, "Working"); await fn(b); });
  act("[data-scandeploy]", b => scannersAct({action: "deploy", node: b.dataset.scandeploy}));
  act("[data-scandeployall]", () => scannersAct({action: "deploy-all"}));
  act("[data-scanupdate]", b => scannersAct({action: "update", node: b.dataset.scanupdate}));
  act("[data-scanrun]", b => scannersAct({action: "run", node: b.dataset.scanrun}));
  act("[data-scanrunall]", () => scannersAct({action: "run"}));
  act("[data-scancheck]", () => scannersAct({action: "check"}));
  act("[data-scanon]", b => scannersAct({action: "schedule", on: b.dataset.scanon === "1"}));
  act("[data-scansave]", () => scannersAct({action: "schedule", cron: scannersCustom ?? root.querySelector("#scanCron")?.value ?? ""}).then(() => { scannersCustom = null; }));
  root.querySelectorAll("[data-scanremove]").forEach(b => b.onclick = async () => {
    const n = (scannersData?.nodes || []).find(x => x.node === b.dataset.scanremove);
    if (!await askYes(`Remove the scanners from ${n?.name || "this node"}? Its images and caches go, and the reports it sent are forgotten.`, {verb: "Remove", danger: true})) return;
    busy(b, "Removing");
    await scannersAct({action: "remove", node: b.dataset.scanremove});
  });
  const when = root.querySelector("#scanWhen");
  if (when) when.onchange = () => {
    if (when.value){ scannersCustom = null; scannersAct({action: "schedule", cron: when.value}); }
    else { scannersCustom = root.querySelector("#scanCron")?.value || scannersData?.schedule?.cron || "0 4 * * 0"; scannersRev++; drawPanes(); }
  };
  const cron = root.querySelector("#scanCron");
  if (cron) cron.oninput = () => { scannersCustom = cron.value; };
  root.querySelectorAll("[data-scanlog]").forEach(a => a.onclick = e => { e.preventDefault(); openJob(a.dataset.scanlog); });
}
