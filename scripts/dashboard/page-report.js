// Report a bug in BuilderBot from a project's row (the operator, 2 Oct): a
// person's way into the same diagnostics a session reaches with
// `bb report`. The dialog asks for a category, what happened and how to make
// it happen; the project is the row's, and the server adds the node and the
// build it was seen on. One classic script beside index.html; the button is
// page-sidebar.js's and the markup #reportModal is index.html's.

"use strict";

// What a report is about, in the words a person would pick. The words go
// into the report's area, which is what the diagnostics sort and read by.
const REPORT_CATS = [
  "The dashboard", "A Claude session", "Builds and tests", "The notebook",
  "Nodes and toolchains", "The emulator or a phone", "Containers", "Git and pushing",
  "Signing", "The companion app", "Something else",
];
let reportProject = "";

function openReport(project){
  reportProject = project;
  const m = $("reportModal");
  armModal(m);
  $("reportTitle").textContent = `Report a bug, from ${project}`;
  const cat = $("reportCat");
  if (!cat.options.length)
    cat.innerHTML = REPORT_CATS.map(c => `<option>${esc(c)}</option>`).join("");
  $("reportText").value = "";
  $("reportRepro").value = "";
  $("reportErrWrap").hidden = true;
  m.hidden = false;
  m.onclick = e => { if (e.target === m) m.hidden = true; };
  $("reportCancel").onclick = () => { m.hidden = true; };
  $("reportSend").onclick = sendReport;
  setTimeout(() => $("reportText").focus(), 50);
}

async function sendReport(){
  const text = $("reportText").value.trim();
  const fail = msg => { $("reportErr").textContent = msg; $("reportErrWrap").hidden = false; };
  if (!text) return fail("say what happened: one sentence is enough");
  const btn = $("reportSend");
  busy(btn, "Sending");
  try{
    const r = await postJSON("/api/reports", {action: "add", project: reportProject, text,
      area: $("reportCat").value, repro: $("reportRepro").value.trim()});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) return fail(j.error || `the controller answered ${r.status}`);
    $("reportModal").hidden = true;
    notify(`reported as #${j.id ?? j.report?.id ?? "?"}: it is in the diagnostics`);
  }catch(e){ fail("could not reach the controller: " + e); }
  finally{ if (btn.isConnected) unbusy(btn, "Send"); }
}
