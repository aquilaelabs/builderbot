// The Analysis tab: the static-analysis findings, filtered by level and
// by text, one document tab (kind: findings).
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

let fxRev = 0;                  // bumped when the filters change, so the pane
let fxProject = "";             // repaints without waiting for a poll
const fxState = {level: "", find: ""};

// The narrowing itself, shared with every notebook's Analysis view: the same
// two filters mean the same thing on both surfaces, and a person who learned
// one has learned the other. `st` is the caller's own {level, find}: the tab
// has one, each notebook has its own, and `redraw` is whatever repaints that
// surface.
function fxFilter(rows, st){
  const q = (st.find || "").trim().toLowerCase();
  return rows.filter(f =>
    (!st.level || f.level === st.level
      || (st.level === "note" && f.level === "info"))
    && (!q || `${f.rule} ${f.path} ${f.message || ""} ${f.desc || ""}`
              .toLowerCase().includes(q)));
}

function fxBarHtml(rows, st, extra){
  const per = {};
  for (const f of rows){
    const l = f.level === "info" ? "note" : f.level;
    per[l] = (per[l] || 0) + 1;
  }
  const lvls = ["error", "warning", "note"].filter(l => per[l]);
  // Classes, not ids: a notebook per project means this bar can exist several
  // times on one page, and duplicate ids are how the wrong one gets wired.
  return `${extra || ""}
    <select class="fxLevel" aria-label="level">
      <option value="">every level</option>
      ${lvls.map(l => `<option value="${esc(l)}"${l === st.level ? " selected" : ""}>${
        esc(l)} · ${per[l]}</option>`).join("")}
    </select>
    <input class="fxFind" maxlength="80" autocomplete="off"
      placeholder="search rules, paths, messages" value="${esc(st.find || "")}">`;
}

// The same bar wearing its own band, for the notebook's Analysis view, which
// renders into a plain list and needs the wrapper the tab's scaffold already
// provides as a slot.
function fxBarBand(rows, st, extra){
  const inner = fxBarHtml(rows, st, extra);
  return inner ? `<div class="field histbar fxbar">${inner}</div>` : "";
}

function fxWireBar(root, st, redraw){
  const sel = root.querySelector(".fxLevel"), inp = root.querySelector(".fxFind");
  if (sel) sel.onchange = () => { st.level = sel.value; redraw(); };
  // Debounced like the history search: a repaint per keystroke redraws the
  // list under the reader's cursor for nothing the last keystroke does not
  // already deliver.
  let t = null;
  if (inp) inp.oninput = () => { clearTimeout(t); t = setTimeout(() => {
    st.find = inp.value; redraw();
  }, 250); };
}

// The one answer, from the poll: no /reports mount, nothing in it, or nothing
// in it that parses: three ways to have nothing, and a control that is off
// wants one of them, not three. Absent (an older server) is not "off", the
// same rule dockerWhy is written to: a page with no opinion leaves the control
// as it was rather than switching it off on a hunch.
const findingsOff = () =>
  state && state.reports_ok === false
    ? (state.reports === false
        ? "no analysis reports: /reports is not mapped in"
        : "nothing readable in /reports: no analysis report there parses")
    : "";

function openFindingsTab(){
  // Ghosted, not silent: the button says why on hover and this is the same
  // sentence, for the paths a disabled button does not cover: a saved layout,
  // a keyboard, a restored tab.
  const off = findingsOff();
  if (off){ notify(off, true); return; }
  openTab({kind: "findings", arg: "__findings", label: "Analysis"});
  loadFindings();
}
