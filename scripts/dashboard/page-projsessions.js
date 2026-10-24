// The foot of a project's settings dialog: every account's sessions on the
// project, for an administrator, each with End (projsessions.py, the
// operator's call of 24 Sep). Ending is the one thing an administrator may
// do to another person's session; keys and typing stay theirs (B172).
// Unlike the settings above it, End acts at once, behind its own confirm,
// the way Delete project does in the same dialog.
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

// Fetched when the gear opens the dialog, and again after an End. Drawn only
// while the dialog is still on the project it was asked for.

"use strict";

async function rnSessionsLoad(name){
  // Not asked for and refused (B89), and not drawn for a role that does
  // not give it (the operator, 21 Oct).
  if (rnSettingsWhy(name)) return;
  let j;
  try{
    j = await (await fetch("/api/project-sessions?project=" + encodeURIComponent(name))).json();
  }catch(e){ return; }
  if (rnFor !== name || rnMode === "git") return;
  if (j.error){ rnWhyOff($("rnSessField"), $("rnSessList"), j.error); return; }
  rnSessionsDraw(name, j.sessions || []);
}

// Whose, what and where on each row; "you" for the reader's own.
const rnSessWho = r => r.who === state?.me ? "you" : r.who;

function rnSessionsDraw(name, rows){
  if (rnMode === "git") return;                    // the remote's door alone (B539)
  const list = $("rnSessList");
  list.innerHTML = rows.length ? rows.map((r, i) => `<div class="row rnsess">
      <div class="grow"><div class="name">${esc(rnSessWho(r))}</div>
        <div class="sub">${[r.kind === "claude" ? "Claude" : "shell",
          r.node ? "on " + esc(r.node) : "", esc(r.state || "")].filter(Boolean).join(" · ")}</div></div>
      <button type="button" class="danger" data-rnsessend="${i}">End</button>
    </div>`).join("") : `<div class="hint">No sessions on this project.</div>`;
  list.querySelectorAll("[data-rnsessend]").forEach(b =>
    // Its own attribute: data-rnend is a section bar's End and save, which
    // the dialog's delegated click took this press for as well.
    b.onclick = () => rnSessionEnd(name, rows[Number(b.dataset.rnsessend)], b));
  $("rnSessField").hidden = false;
}

async function rnSessionEnd(name, r, btn){
  const whose = r.who === state?.me ? "your" : `${r.who}'s`;
  if (!await askYes(r.kind === "claude"
      ? `End ${whose} Claude session on ${projLabel(name)}?\n\nThe work in flight stops; the conversation resumes from the Claude button.`
      : `End ${whose} shell on ${projLabel(name)}?\n\nWhatever is running in it stops.`)) return;
  busy(btn, "Ending");
  try{
    const j = await (await postJSON("/api/project-sessions",
      {project: name, action: "end", session: r.name, node: r.node_id || ""})).json();
    if (j.error){ notify(j.error, true); unbusy(btn, "End"); return; }
    notify(`ended ${whose} ${r.kind === "claude" ? "Claude session" : "shell"} on ${projLabel(name)}`);
  }catch(e){ notify("could not end it: " + failWords(e), true); unbusy(btn, "End"); return; }
  rnSessionsLoad(name);
}
