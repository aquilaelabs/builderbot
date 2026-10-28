// The Audit page (R158 step 8), Controller's, for an account that reads
// the controller's area: who did what to this install, from the audit
// trail every mutation lands in (db.audit), newest first, a page at a time
// (the long-lists rule), narrowed to one person or one machine with the
// two pickers in the bar. Nothing here changes anything.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// GET /api/audit, read when the page opens, on a filter and for older rows.

"use strict";

let auditData = null;            // {rows, total, people, machines}, or null before the first read
let auditErr = "";
let auditRev = 0;
let auditPerson = "", auditMachine = "";

function openAuditTab(){
  openTab({kind: "audit", arg: "__audit", label: "Audit"});
}

async function loadAudit({older = false} = {}){
  const q = new URLSearchParams();
  if (auditPerson) q.set("person", auditPerson);
  if (auditMachine) q.set("machine", auditMachine);
  const have = older ? (auditData?.rows || []) : [];
  if (older && have.length) q.set("before", String(have[have.length - 1].at));
  try{
    const j = await (await fetch("/api/audit?" + q.toString())).json();
    if (j.error){ auditErr = j.error; }
    else{
      auditErr = "";
      // Older rows join under the ones on screen, which never move
      // (long-lists); a fresh read replaces them.
      auditData = {...j, rows: older ? [...have, ...j.rows] : j.rows};
    }
  }catch(e){ auditErr = "audit: " + failWords(e); }
  auditRev++;
  if (tabs.some(t => t.kind === "audit")) drawPanes();
}

const AUDIT_COLS = [{label: "When", w: "7rem"}, {label: "Who", w: "minmax(0,.7fr)"}, {label: "Did"}, {label: "On"}];

// A row's "On": the machine by its name where the target is one, else the
// target as recorded (a project, an account, a container).
function auditRows(rows){
  if (!rows.length) return `<div class="empty">nothing recorded${auditPerson || auditMachine ? " for this pick" : " yet"}</div>`;
  return tblWrap(AUDIT_COLS, rows.map(r => `<div class="row auditrow" title="${esc(new Date(r.at * 1000).toLocaleString())}">${tblLine(AUDIT_COLS, [
    esc(ago(r.at)), esc(r.who), esc(r.action), esc(r.machine || r.target || "")])}</div>`).join(""), "audittbl");
}

function renderAuditInto(i){
  const d = docSurface(i, "audit");
  if (!d) return;
  const data = auditData;
  const pick = (id, label, opts, now) => `<label class="pick"><span class="pickw">${label}</span>
    <select id="${id}"><option value=""${now ? "" : " selected"}>any</option>${opts.map(([v, l]) =>
      `<option value="${esc(v)}"${v === now ? " selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
  d.setBar(data ? `<span class="sp"></span><span class="actbar">${
      pick("auditPerson", "Person", (data.people || []).map(p => [p, p]), auditPerson)}${
      pick("auditMachine", "Machine", (data.machines || []).map(m => [m.id, m.name]), auditMachine)}</span>` : "");
  if (data === null){
    d.list.innerHTML = auditErr ? `<div class="field"><div class="notice bad">${esc(auditErr)}</div></div>`
      : skTpl(pageHead({facts: [["Recorded", GHOST], ["Shown", GHOST]]})
        + docSection("audit", "trail", "What was done", "", skRows(6)));
    if (!auditErr) loadAudit();
    return;
  }
  const rows = data.rows || [];
  d.list.innerHTML = pageHead({facts: [["Recorded", String(data.total || 0)], ["Shown", String(rows.length)],
      ["Since", rows.length ? new Date(rows[rows.length - 1].at * 1000).toLocaleDateString() : ""]]})
    + (auditErr ? `<div class="notice bad">${esc(auditErr)}</div>` : "")
    + docSection("audit", "trail", "What was done", String(data.total || 0), auditRows(rows));
  wireAudit(d.el);
  const tbl = d.el.querySelector(".audittbl");
  if (tbl) paginate(tbl, ":scope > .auditrow", {key: "auditList", noun: "entries", total: data.total || rows.length,
                                               more: () => loadAudit({older: true})});
}

function wireAudit(root){
  wireSections(root);
  const on = (id, fn) => { const el = root.querySelector("#" + id); if (el) el.onchange = () => fn(el.value); };
  on("auditPerson", v => { auditPerson = v; loadAudit(); });
  on("auditMachine", v => { auditMachine = v; loadAudit(); });
}
