// The notebook's approval queue (roadmap #27): what a session added under
// ask, waiting on the operator. One classic script beside index.html
// (docs/nodes.md §13): one file per notebook view (R60). A factory
// makeNotebook calls per notebook.
function nbPendingView({$, nb, project, root}){
  // ---- what a session has waiting for approval (roadmap #27) --------------
  async function loadPending(again = false){
    try{
      const r = await fetch(`/api/pending?project=${encodeURIComponent(project)}`);
      const j = await r.json();
      if (j.error) return;
      nb.pendData = j;
    }catch(e){ return; }
    // The answer's own revision, not the page's token as of now (B201), so
    // the nb.watch above can tell a later move from what this copy holds.
    nb.pendRev = nb.pendData.rev ?? revs[`pending:${project}`] ?? nb.pendRev ?? 0;
    drawPending();
    // Already behind (see nb-tests.js): read once more now.
    if (!again && nb.pendData.rev !== undefined && revs[`pending:${project}`] !== undefined
        && revs[`pending:${project}`] !== nb.pendData.rev) return loadPending(true);
  }
  function drawPending(){
    const el = $("nbPending");
    if (!el) return;
    const rows = nb.pendData?.pending || [];
    const n = rows.length;
    // The strip's own counts, per tab: a number where the tab is, so the
    // question "which of these" is answered without opening anything.
    for (const b of root.querySelectorAll(".nbtabs button")){
      const k = {roadmap: "roadmap", bugs: "bugs", briefing: "rules"}[b.dataset.v];
      let badge = b.querySelector(".pcount");
      const c = k ? (nb.pendData?.counts?.[k] || 0) : 0;
      if (!c){ if (badge) badge.remove(); continue; }
      if (!badge){ badge = document.createElement("span"); badge.className = "pcount"; b.appendChild(badge); }
      badge.textContent = String(c);
    }
    el.hidden = !n;
    if (!n){ el.innerHTML = ""; return; }
    const c = nb.pendData.counts || {};
    const parts = [["roadmap", "roadmap"], ["bugs", "bug"], ["rules", "rule"], ["settings", "setting"]]
      .filter(([k]) => c[k]).map(([k, w]) => `${c[k]} ${w}${c[k] === 1 || w === "roadmap" ? "" : "s"}`);
    el.innerHTML = `<div><span>${n} change${n === 1 ? "" : "s"} from a session
        ${n === 1 ? "is" : "are"} waiting for your approval${parts.length ? ": " + esc(parts.join(", ")) : ""}.</span>
        <button type="button" id="nbReview">Review</button></div>`;
    $("nbReview").onclick = () => openPending(project);
  }

  // Which view a new notebook opens on: the one this browser last had it on,
  // when that is still a view the strip has, so a reload lands where you
  // were, and otherwise the first tab of the strip, read from the strip
  // rather than marked on one of the buttons, so that reordering it moves
  // the default with it and the two cannot drift apart.
  //
  // That it is only set HERE is the rest of the behaviour: this clone is
  // parked and reused while the tab is on the strip, so leaving the tab and
  // coming back finds the view where you left it, and closing the tab
  // destroys the instance (see hideTab), which forgets the view, so the next
  // open is a new clone that starts on the strip's first view again.
  //
  // Last in this function on purpose: the panel can open on any view now,
  // and each view's first draw reads bindings declared all the way down
  // here: a `let` read before its initializer takes the whole tab down,
  // which is bug #27's shape.
  {
    const was = nbViewMemo.read()[project];
    nb.setNbView((was && root.querySelector(`.nbtabs button[data-v="${CSS.escape(was)}"]`)
                 ? was : root.querySelector(".nbtabs button").dataset.v));
  }

  // The project's containers, from the manager's own answer for the
  // project's node: its instances and anything shown under it. Drawn with
  // the Docker tab's rows and wired with its handlers, so Up, Down, Env and
  // Rebuild here are the same controls. Re-read while a job runs, on the
  // poll, since the row's tail and state move then.

  return {loadPending, drawPending};
}

// ---- the review modal (roadmap #27) --------------------------------------
// Top-level rather than the notebook's, because the bell reaches it too. It
// draws from one fetch and redraws from the answer to its own action, so a
// row is never ticked twice: what was approved is gone from the reply.
// Moved here from index.html with bb map sections in hand: the modal is the
// pending feature's, and a feature lives in one file.

let pendFor = null;

async function openPending(project){
  pendFor = project;
  $("pendTitle").textContent = `Waiting for your approval: ${project}`;
  $("pendModal").hidden = false;
  $("pendList").innerHTML = "";
  $("pendEmpty").hidden = true;
  $("pendHint").textContent = "Loading…";
  try{
    const r = await fetch(`/api/pending?project=${encodeURIComponent(project)}`);
    drawPendingModal(await r.json());
  }catch(e){ $("pendHint").textContent = "Could not read what is waiting."; }
}

function drawPendingModal(j){
  if (pendFor === null) return;
  const rows = j?.pending || [];
  const gate = j?.gate || {};
  const held = ["roadmap", "bugs", "rules"].filter(k => gate[k] === "ask");
  $("pendHint").textContent = rows.length
    ? `A session added these while ${pendFor} is set to ask for ${held.join(", ") || "nothing"}. `
      + `Approve to apply them; deny to drop them and anything that depends on them.`
    : "";
  $("pendEmpty").hidden = !!rows.length;
  // With nothing waiting, the empty list's border, a Select all over nothing
  // and a blank hint were three bands of chrome around one sentence.
  $("pendAllF").hidden = $("pendListF").hidden = !rows.length;
  $("pendHintF").hidden = !rows.length && !$("pendHint").textContent;
  $("pendApprove").disabled = $("pendDeny").disabled = !rows.length;
  $("pendApprove").hidden = $("pendDeny").hidden = !rows.length;
  const NAMES = {roadmap: "Roadmap", bugs: "Bugs", rules: "Rules", settings: "Build and test"};
  const tag = r => r.kind === "roadmap" && r.number != null ? `R${r.number}`
             : r.kind === "bugs" && r.number != null ? `B${r.number}`
             : r.kind === "rules" && r.number ? String(r.number) : "";
  const detail = r => {
    const a = r.args || {};
    const bits = [];
    if (r.kind === "roadmap" && r.verb === "add"){
      (a.steps || []).forEach((st, i) => bits.push(`${i + 1}. ${st}`));
    } else if (r.kind === "roadmap"){ bits.push(a.text || a.why || ""); }
    else if (r.kind === "bugs" && r.verb === "add"){
      for (const k of ["area", "repro", "expected", "actual", "notes"]) if (a[k]) bits.push(`${k}: ${a[k]}`);
    } else if (r.kind === "bugs"){ for (const k of Object.keys(a)) if (!["bug_id", "act"].includes(k)) bits.push(`${k}: ${a[k]}`); }
    else if (r.kind === "rules"){
      bits.push(a.text || "");
      if (a.paths) bits.push(`files: ${Array.isArray(a.paths) ? a.paths.join(", ") : a.paths}`);
      if (a.words) bits.push(`words: ${Array.isArray(a.words) ? a.words.join(", ") : a.words}`);
    } else if (r.kind === "settings"){
      for (const k of ["build", "test", "outputs"]) if (a[k]) bits.push(`${k}: ${Array.isArray(a[k]) ? a[k].join(", ") : a[k]}`);
    }
    return bits.filter(Boolean).join("\n");
  };
  const when = t => fmtTime((t || 0) * 1000, {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"});
  let html = "", last = null;
  for (const r of rows){
    if (r.kind !== last){ html += `<div class="pkind">${NAMES[r.kind] || esc(r.kind)}</div>`; last = r.kind; }
    const d = detail(r);
    html += `<label class="prow${r.after != null ? " dep" : ""}" data-id="${r.id}">
      <input type="checkbox" checked data-pend="${r.id}" data-after="${r.after ?? ""}">
      <span><span class="psum">${tag(r) ? `<b>${esc(tag(r))}</b> · ` : ""}${esc(r.summary || "")}</span>
        <div class="pwhen">${esc(when(r.at))}${r.after != null ? " · needs the change above" : ""}</div>
        ${d && d !== r.summary ? `<details${sectAttr("pending:full:" + r.id)}><summary>full text</summary><pre>${esc(d)}</pre></details>` : ""}
      </span></label>`;
  }
  $("pendList").innerHTML = html;
  $("pendAllBox").checked = !!rows.length;
  $("pendAllBox").indeterminate = false;
  const boxes = () => [...$("pendList").querySelectorAll("input[data-pend]")];
  const sync = () => {
    const on = boxes().filter(b => b.checked).length;
    $("pendAllBox").checked = on > 0 && on === boxes().length;
    $("pendAllBox").indeterminate = on > 0 && on < boxes().length;
    $("pendApprove").disabled = $("pendDeny").disabled = !on;
  };
  $("pendAllBox").onchange = () => { boxes().forEach(b => { b.checked = $("pendAllBox").checked; }); sync(); };
  boxes().forEach(b => b.onchange = () => {
    // Unticking a parent unticks what rides behind it: those cannot land
    // without it, and approving them alone is only a skip.
    if (!b.checked) boxes().filter(x => x.dataset.after === b.dataset.pend).forEach(x => { x.checked = false; });
    sync();
  });
}

async function pendAct(action){
  const project = pendFor;
  const ids = [...$("pendList").querySelectorAll("input[data-pend]:checked")].map(b => Number(b.dataset.pend));
  if (!project || !ids.length) return;
  const btn = action === "approve" ? $("pendApprove") : $("pendDeny");
  busy(btn, action === "approve" ? "Approving" : "Denying");
  try{
    const r = await postJSON("/api/pending", {project, action, ids});
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    const said = [];
    if (j.approved?.length) said.push(`${j.approved.length} approved`);
    if (j.denied?.length) said.push(`${j.denied.length} denied`);
    if (j.skipped?.length) said.push(`${j.skipped.length} skipped: ${j.skipped[0].why}`);
    if (j.failed?.length) said.push(`${j.failed.length} could not be applied: ${j.failed[0].why}`);
    notify(`${project}: ${said.join(", ") || "nothing changed"}`, !!j.failed?.length);
    drawPendingModal(j);
    // The lists moved under the notebook: re-read whichever views exist.
    const nb = notebooks.get(project);
    if (nb){ nb.reload?.(); nb.reloadBugs?.(); nb.reloadMemory?.(); nb.reloadPending?.(); }
    refresh();
  }catch(e){ notify("could not reach the dashboard", true); }
  finally{ unbusy(btn, action === "approve" ? "Approve" : "Deny"); }
}
