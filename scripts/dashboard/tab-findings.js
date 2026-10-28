// The Analysis tab: the static-analysis findings, filtered by level and
// by text, one document tab (kind: findings).
// One classic script beside index.html (docs/design-language.md, Files): pure
// declarations, nothing runs at load.

"use strict";

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

// `dead`: the page's placeholder (R218, the operator 18 Oct), the same
// controls there and dead until the findings land.
function fxBarHtml(rows, st, extra, dead = false){
  const per = {};
  for (const f of rows){
    const l = f.level === "info" ? "note" : f.level;
    per[l] = (per[l] || 0) + 1;
  }
  const lvls = ["error", "warning", "note"].filter(l => per[l]);
  // Classes, not ids: a notebook per project means this bar can exist several
  // times on one page, and duplicate ids are how the wrong one gets wired.
  return `${extra || ""}
    <select class="fxLevel" aria-label="level"${dead ? " disabled" : ""}>
      ${optionList([["", "every level"], ...lvls.map(l => [l, `${l} · ${per[l]}`])], st.level)}
    </select>
    <input class="fxFind" type="search" maxlength="80" autocomplete="off" aria-label="search the findings"
      placeholder="search rules, paths, messages" value="${esc(st.find || "")}"${dead ? " disabled" : ""}>`;
}

// The same bar wearing its own band, for the notebook's Analysis view, which
// renders into a plain list and needs the wrapper the tab's scaffold already
// provides as a slot.
function fxBarBand(rows, st, extra){
  const inner = fxBarHtml(rows, st, extra);
  return inner ? `<div class="field histbar fxbar ctlrow">${inner}</div>` : "";
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
// wants one of them, not three. Absent (a payload that has not landed yet)
// is not "off", the same rule dockerWhy is written to: a page with no opinion leaves the control
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

// ---- findings --------------------------------------------------------

const LEVEL_ORDER = {error:0, warning:1, note:2, info:2, none:3};
const levelClass = l => l === "error" ? "bad" : l === "warning" ? "warn"
                      : (l === "note" || l === "info") ? "note" : "";

// The reports' mtime as of the last load, so a scan re-run on the host shows
// up on its own: the status poll carries the current mtime, and a mismatch
// while a findings tab is open triggers a reload. Only then: reloading on a
// timer would fight the reader for the page (their collapsed sections do
// survive, but their scroll position does not).
let findingsMtime = null;

async function loadFindings(force){
  if (findings && !force) return;
  findingsMtime = state?.reports_mtime ?? null;
  findings = {loading: true};
  try{
    const r = await fetch("/api/findings");
    findings = await r.json();
  }catch(e){ findings = {error: String(e)}; }
  // The Analysis tab repaints if one is open: it draws "loading…" while the
  // fetch is in flight, and a fetch that completes without saying so leaves
  // that word on the pane until some unrelated revision moves. Only then:
  // notebooks call this too, and an unconditional drawPanes() from THEIR
  // fetches landed mid pane-swap in flows that had nothing to do with
  // findings, which is how the Resume test started failing on a tab this
  // never touches.
  if (tabs.some(t => t.kind === "findings")){
    fxRev++;
    drawPanes();
  }
}

// Every project section starts collapsed: the summary line of pills is the
// overview, and the reader opens what they mean to triage. Which sections they
// have opened is kept across re-renders so a reload does not undo it.
const opened = new Set();

// The per-rule rendering the notebook's Analysis view uses: worst level
// first, each rule one block with its hits. What used to be the whole-report
// tab, scoped to one project: the grouping by project became the notebook.
// Which rules are open, by id, so a redraw (the poll, a filter) draws them
// open again (the fold rule: a fold is remembered); recorded by fxRemember,
// which index.html hands the page's toggle listener.
const fxOpen = new Set();
function fxRemember(e){
  const d = e.target;
  if (!(d instanceof HTMLDetailsElement) || !d.classList.contains("rule") || !d.dataset.key) return;
  if (d.open) fxOpen.add(d.dataset.key); else fxOpen.delete(d.dataset.key);
}
function findingsRulesHtml(rows){
  const by = (xs, k) => xs.reduce((m, x) => ((m[x[k] ?? "none"] ??= []).push(x), m), {});
  const rules = by(rows, "rule");
  for (const k of Object.keys(rules))
    rules[k].sort((a, b) => (LEVEL_ORDER[a.level] ?? 9) - (LEVEL_ORDER[b.level] ?? 9));
  const order = Object.keys(rules).sort((a, b) =>
    (LEVEL_ORDER[rules[a][0].level] ?? 9) - (LEVEL_ORDER[rules[b][0].level] ?? 9)
    || rules[b].length - rules[a].length);
  // A rule is a row that opens (R234, rows-you-open): closed, the level,
  // the rule, how many places and the first of them; open, every place, the
  // description, the message whole and the CVEs. The whole message on every
  // closed row made a report a wall.
  let html = "";
  for (const rid of order){
    const hits = rules[rid];
    const f = hits[0];
    const cves = [...new Set(hits.flatMap(h => h.cves))];
    html += `<details class="rule chev" data-key="${esc(rid)}"${fxOpen.has(rid) ? " open" : ""}>
      <summary class="rid">
        <span class="pill ${levelClass(f.level)}">${esc(f.level)}</span>
        <span class="rname">${f.uri ? `<a href="${esc(f.uri)}" target="_blank" rel="noopener">${esc(rid)}</a>`
                : esc(rid)}</span>
        <span class="loc">${esc(f.path)}:${f.line}${hits.length > 1 ? ` <span class="dim">and ${hits.length - 1} more</span>` : ""}</span>
      </summary>
      <div class="rbody">
        <div class="desc">${esc(f.desc || "(no description)")}</div>
        ${cves.map(c => `<a class="cve" target="_blank" rel="noopener"
            href="https://nvd.nist.gov/vuln/detail/${esc(c)}">${esc(c)}</a>`).join("")}
        ${hits.length > 1 ? `<div>${hits.map(h => `<div class="loc">${esc(h.path)}:${h.line}</div>`).join("")}</div>` : ""}
        ${f.message && f.message !== f.desc
            ? `<div class="msg">${esc(f.message)}</div>` : ""}
      </div>
    </details>`;
  }
  return html;
}

// ---- the findings tab, drawn --------------------------------------------

// A finding that places in no project still places somewhere on the page.
// The name cannot collide: a real project cannot contain a space.
const fxProj = f => f.project || "unattributed paths";

function fxRows(){
  const all = (findings?.reports || []).flatMap(r => r.findings || []);
  return fxFilter(all.filter(f => !fxProject || fxProj(f) === fxProject), fxState);
}

function renderFindingsInto(i){
  // Chrome from the scaffold, content from here: the shape every document
  // tab renders in now, so the bands cannot drift per tab (see docSurface).
  const d = docSurface(i, "fx");
  if (!d) return;
  d.bar.classList.add("fxbar");
  if (!findings){
    // The status poll drops the cache when a scan re-runs on the host, and a
    // repaint is not a fetch, so an open tab has to start one itself.
    // loadFindings repaints on completion for every caller.
    loadFindings();
  }
  if (!findings || findings.loading){
    // Its template (R218 step 16): the bar's three narrowing controls stand
    // where they will, their boxes shimmering; the findings are on their way.
    d.setBar(fxBarHtml([], fxState, `<select aria-label="project" disabled><option>all projects</option></select>`, true));
    // As it lands across projects: a project's name over its card.
    d.list.innerHTML = skTpl(`<div class="fxproj"><span class="name">${skv(8)}</span></div>${skRows(6)}`);
    return;
  }
  if (findings.error){
    d.list.innerHTML = `<div class="hint bad">${esc(findings.error)}</div>`;
    return;
  }
  if (findings.available === false){
    // How to set the scanners up, one press away in Help (docs/scanners.md).
    d.list.innerHTML = `<div class="empty">no scanner reports yet: the Scanners page under Containers
      deploys BuilderBot's scanners to each node and runs them on a schedule, and what they send up lands here.
      <a href="#/help/scanners">The scanners</a> says how.</div>`;
    return;
  }
  const rows = fxRows();
  const all = (findings.reports || []).flatMap(r => r.findings || []);
  const perProject = {};
  for (const f of all) perProject[fxProj(f)] = (perProject[fxProj(f)] || 0) + 1;
  // Real projects alphabetical, the unplaceable bucket last; it is a note
  // about the report, not a project to pick among them.
  const projects = Object.keys(perProject).sort((a, b) =>
    (a === "unattributed paths") - (b === "unattributed paths") || a.localeCompare(b));
  const projSelect = `<select id="fxProject" aria-label="project">
      ${optionList([["", `all projects · ${all.length}`], ...projects.map(pn => [pn, `${projLabel(pn)} · ${perProject[pn]}`])], fxProject)}
    </select>`;
  // Grouped by project when looking across them, flat when one is chosen:
  // a heading repeating the selector's own value is noise.
  const by = {};
  for (const f of rows) (by[fxProj(f)] ??= []).push(f);
  const groups = fxProject ? [["", rows]] : Object.entries(by).sort((a, b) =>
    (a[0] === "unattributed paths") - (b[0] === "unattributed paths")
    || a[0].localeCompare(b[0]));
  // Inside .fx, because that is the container the notebook's Analysis view
  // renders rules into and every .rule style is scoped to it: same data,
  // same rendering, one implementation and one stylesheet for both.
  const body = rows.length
    ? groups.map(([name, fs]) => (name
        ? `<div class="fxproj"><span class="name">${esc(name === "unattributed paths" ? name : projLabel(name))}</span>
             <span class="dim">${fs.length}</span></div>` : "")
        + `<div class="fx">${findingsRulesHtml(fs)}</div>`).join("")
    : `<div class="empty">${all.length
        ? "nothing matches the filters"
        : "no findings in the current reports. A report lists what it found, "
          + "not what it checked."}</div>`;
  d.setBar(fxBarHtml(all.filter(f => !fxProject || fxProj(f) === fxProject),
                     fxState, projSelect));
  d.list.innerHTML = body;
  const aside = findings.aside ? `${findings.aside} finding(s) are
      against paths that are no project's and are counted aside rather than
      listed${(state?.findings_heads || []).length
        ? ": " + (state.findings_heads || []).map(h =>
            `${esc(h.head)} <span class="dim">× ${h.n}</span>`).join(" · ")
        : ""}` : "";
  const ages = reportAges();
  d.setFoot([aside, ages].filter(Boolean).join("<br>"));
  const redraw = () => { fxRev++; drawPanes(); };
  $("fxProject").onchange = e => { fxProject = e.target.value; redraw(); };
  fxWireBar(d.el, fxState, redraw);
}
