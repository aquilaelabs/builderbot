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
    const parts = [["roadmap", "roadmap"], ["bugs", "bug"], ["rules", "rule"]]
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
