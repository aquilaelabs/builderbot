// The document-tab scaffold: a document tab's surface, its sections (folds
// that stay the way they were left), the lanes and diffs the Git view
// draws, and the busy state a button wears while its request runs.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- the document-tab scaffold ------------------------------------------

// Every document tab is the same five slots in the same order, and every tab
// that wrote its own copy of them drifted: a bar with no inset, rows on the
// sidebar's tighter padding, an error state flush against the edge. Three of
// those shipped and were fixed by inverting a mechanism each time; this is
// the last inversion: the chrome is built HERE, once, and a renderer fills
// slots instead of writing chrome. The conformance suite (test/uniform.mjs)
// holds every kind to the result, so a new tab that skips this reads as a
// failure, not as a style.
//
//   const d = docSurface(i, "nodes");
//   d.bar.innerHTML  = ...   // filters/actions: a .field histbar, pre-made
//   d.list.innerHTML = ...   // the bands: .row / .rule / .empty / .loading
//   d.foot.innerHTML = ...   // the quiet footer line (.fnote), or leave empty
//
// Returns null when the pane is gone (a tab closed under a slow fetch), so
// callers bail with `if (!d) return;` instead of drawing into nothing.
// The node switcher every node-scoped tab wears (R121, the operator 4 Oct):
// the same label, the same place (the bar's left, verbs at its right) and the
// same list on Toolchains, the Emulator, the Phone and the CI runner. A node
// that cannot be picked for this tab says why in its option, and a quiet one
// says so. `why(n)` is "" for one that can.
function nodePick(id, nodes, cur, why = () => ""){
  if (!nodes.length) return "";
  return `<label class="pick">Node <select id="${esc(id)}" aria-label="node">${nodes.map(n => {
    const w = why(n);
    return `<option value="${esc(n.id)}"${n.id === cur ? " selected" : ""}${w ? " disabled" : ""}>${esc(n.name)}${
      w ? `: ${esc(w)}` : n.live === false ? " (quiet)" : ""}</option>`;
  }).join("")}</select></label>`;
}

// What a list, a grid or a page is waiting with (R218 step 15, the operator
// 16 Oct): shapes laid out the way its content will land, shimmering, where
// a "loading…" line said the same in words. Still a .loading, so everything
// that knew a placeholder knows this one: paint() fades in what replaces it,
// the poll's failure notice writes its words over it, a suite waits for it
// to go. The words stay for a screen reader. A shape: rows (a list), cards
// (a grid of cards), tiles (a row of numbers), home (Home's tiles and two
// cards), lines (a page of text, a log, a diff), chips (a row of buttons),
// word (inline, a view's head while its count is coming).
const SKW = [62, 48, 71, 55, 66, 43, 58, 51];
function skel(shape = "rows", n = 0, said = "loading…"){
  if (SKTPLS[shape]) return SKTPLS[shape]();
  const b = (cls, w) => `<i class="sk-b${cls ? " " + cls : ""}"${w ? ` style="width:${w}%"` : ""}></i>`;
  const times = (k, f) => Array.from({length: k}, (_, j) => f(j)).join("");
  const rows = k => times(k, j => `<div class="sk-row">${b("", SKW[j % 8])}${b("sub", SKW[(j + 3) % 8] / 2)}</div>`);
  const tiles = k => `<div class="sk-tiles">${times(k, j => `<div class="sk-tile">${b("big", 30 + SKW[j % 8] / 4)}${b("sub", SKW[(j + 2) % 8])}</div>`)}</div>`;
  const card = j => `<div class="sk-card">${b("", 35 + SKW[j % 8] / 3)}${b("sub", 80)}${b("sub", SKW[(j + 1) % 8])}</div>`;
  const inner = {
    rows: () => rows(n || 5),
    cards: () => `<div class="sk-cards">${times(n || 6, card)}</div>`,
    tiles: () => tiles(n || 6),
    home: () => tiles(6) + `<div class="sk-cards two">${times(2, j => `<div class="sk-card">${b("", 30)}${rows(4 - j)}</div>`)}</div>`,
    lines: () => times(n || 7, j => b("line", j % 4 === 3 ? 30 : 40 + SKW[j % 8] * .7)),
    chips: () => times(n || 6, j => b("chip", 0)),
    word: () => b("", 0),
  }[shape] || (() => rows(n || 5));
  const tag = shape === "word" ? "span" : "div";
  return `<${tag} class="loading skel sk-${esc(shape)}"><span class="sk-said">${esc(said)}</span>${inner()}</${tag}>`;
}

// ...and a page that knows its own shape better than that (R218 step 16, the
// operator 16 Oct): what never changes on it (its headings, a tile's label,
// a table's head, a form's labels) drawn for real, and only the values on
// their way shimmering. skTpl() keeps it a .loading, with the word for a
// screen reader; skv() is one value inline, as wide as a typical one in em
// ("ctl" for a field's control, the height of one);
// skRows() rows inside a real section or card.
function skv(em = 5, cls = ""){ return `<i class="skv${cls ? " " + esc(cls) : ""}" style="width:${Number(em) || 5}em"></i>`; }
function skRows(n = 4){
  return Array.from({length: n}, (_, j) => `<div class="sk-row"><i class="sk-b" style="width:${SKW[j % 8]}%"></i><i class="sk-b sub" style="width:${SKW[(j + 3) % 8] / 2}%"></i></div>`).join("");
}
// Inert unless its caller wired what it drew (`live`): a form drawn before
// its wiring would take typing the real one, landing, throws away.
// Its sections lose their keys: drawn open or shut as the real ones will
// be, but never found by a selector, a wiring or a suite asking for those.
function skTpl(html, {said = "loading…", live = false} = {}){
  return `<div class="loading skel skt"${live ? "" : " inert"}><span class="sk-said">${esc(said)}</span>${
    html.replace(/ data-sect="[^"]*"/g, "")}</div>`;
}

// The bar a node's page wears (nodePick and its actions at the right) while
// what it lists is on its way: the picker's box shimmering, the actions
// there and dead until the page they act on has drawn. An action given as
// [label, "primary"] is the page's main action and wears its fill.
function skNodeBar(actions = []){
  return `<label class="pick">Node ${skv(7, "ctl")}</label><span class="sp"></span><span class="actbar">${
    actions.map(a => [].concat(a)).map(([a, cls]) => `<button type="button"${cls ? ` class="${esc(cls)}"` : ""} disabled>${esc(a)}</button>`).join("")}</span>`;
}
// ---- the first paint, shaped like the page the address names ----------------
// What a reload shows until the first snapshot lands (the operator, 17 Oct:
// a refresh on Projects showed full-width rows, no rail and no bar). The
// rail's groups, inert until drawRail replaces them; the pane's bar as the
// page will wear it (its group's tools, or a project's header and its view
// strip); and the page's own shape in a document's frame. Its own class
// names, not the pane's .stack, so the first real draw builds the pane
// afresh rather than inside it.
function bootPage(hash){
  const parts = String(hash || "").replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "machines" && parts[1] === "nginx") parts[0] = "containers";   // openRoute's alias
  const key = parts[0] || "home", g = RAIL.find(x => x.key === key) || RAIL[0];
  const tool = g.tools.some(([k]) => k === parts[1]) ? parts[1] : g.tools[0][0];
  const seg = (tools, on) => `<span class="subnav pseg">${tools.map(([k, label]) =>
      `<button type="button" disabled class="${k === on ? "on" : ""}">${esc(label)}</button>`).join("")}</span>`;
  const doc = (barHtml, body) => `<div class="doc on flush"><div class="doctab">${barHtml
    ? `<div class="field histbar docbarrow">${barHtml}</div>` : ""}<div class="doclist">${body}</div></div></div>`;
  let bar, body;
  if (key === "projects" && parts[1] && !g.tools.some(([k]) => k === parts[1] || (k === "findings" && parts[1] === "analysis"))){
    // A project's notebook: its header, its view strip under it the
    // pane's width with the view's group open, then rows.
    const GROUPS = [["overview", "Overview", [["overview", "Overview"], ["settings", "Settings"]]],
                    ["plan", "Plan", [["roadmap", "Roadmap"], ["bugs", "Bugs"]]],
                    ["code", "Code", [["git", "Git"], ["tests", "Tests"], ["analysis", "Analysis"]]],
                    ["ship", "Ship", [["artifacts", "Artifacts"], ["docker", "Docker"]]],
                    ["docs", "Docs", [["design", "Design"], ["wiki", "Wiki"]]]];
    const view = parts[2] || "overview", grp = GROUPS.find(x => x[2].some(([v]) => v === view)) || GROUPS[0];
    const btn = (on, w) => `<button type="button" disabled class="${on ? "on" : ""}">${w}</button>`;
    bar = `<span class="phead"><span class="pname">${skv(6)}</span><span class="pfacts">${skv(14)}</span><span class="sp"></span>
      <button type="button" disabled>Open Claude</button><button type="button" disabled>Shell</button></span>`;
    body = `<div class="doc on nbhost"><div class="nb"><div class="nbtabs"><div class="nbgroups">${GROUPS.map(([k, w]) => btn(k === grp[0], w)).join("")}</div>
      <div class="nbsub">${grp[2].map(([v, w]) => btn(v === view, w)).join("")}</div></div>
      <div class="nbview"><div class="field">${skRows(5)}</div></div></div></div>`;
    return {rail: key, bar: `<div class="bar proj">${bar}</div>`, body: `<div class="skstack">${body}</div>`};
  }
  bar = `<div class="bar page">${seg(g.tools, key === "projects" && parts[1] === "analysis" ? "findings" : tool)}</div>`;
  if (key === "home")
    // Home's own order: the tiles, Attention and Last jobs, the projects at
    // a glance, each heading drawn and what fills it shimmering.
    body = doc("", `<div class="field"><div class="tiles hometiles">${["nodes online", "containers running", "jobs running",
        "sessions open", "updates due", "CI red"].map(l => `<span class="tile"><span class="tv">${skv(1.4)}</span><span class="tl">${l}</span></span>`).join("")}</div></div>
      <div class="field"><div class="homegrid"><section class="hcard"><h3>Attention</h3>${skRows(2)}</section>
        <section class="hcard"><h3>Last jobs</h3>${skRows(3)}</section></div></div>
      <div class="field"><section class="hsect"><h3>Projects at a glance</h3>${skRows(2)}</section></div>`);
  else if (key === "projects" && tool === "projects")
    body = doc(`<input type="search" disabled placeholder="name, branch or node"><span class="sp"></span>
      <span class="actbar"><button type="button" disabled>${BIN}</button><button type="button" class="primary" disabled>New project</button></span>`,
      `<div class="field pgridband"><div class="pgrid">${Array.from({length: 6}, (_, j) =>
        `<div class="sk-card skpcard"><i class="sk-b" style="width:${SKW[j % 8] / 2 + 20}%"></i><i class="sk-b sub" style="width:70%"></i><i class="sk-b sub" style="width:${SKW[(j + 3) % 8] / 2}%"></i></div>`).join("")}</div></div>`);
  // The rest: their rows in a floating card, as the pages draw them at a
  // desk (their exact first paints are R218's templates step).
  else body = doc("", `<div class="field"><div class="sk-card skrows">${skRows(6)}</div></div>`);
  return {rail: key, bar, body: `<div class="skstack">${body}</div>`, tool: key === "projects" && parts[1] === "analysis" ? "findings" : tool};
}

// ...and in it, the page's own placeholder where it has one: the page drawn
// by its own render into the boot's frame (doc "boot") with nothing loaded
// yet, which is what a page opened by a press shows while it waits (the
// operator, 18 Oct: a reload showed a placeholder of its own and then the
// page's). A page that cannot draw before the first status read keeps the
// boot's shape.
function bootOwn(root, tool){
  const doc = root?.querySelector(".skstack > .doc");
  const spec = TABKINDS[tool];
  if (!doc || !spec?.render || tool === "projects") return;
  const was = doc.innerHTML;
  doc.id = "docboot";
  doc.innerHTML = "";
  try{ spec.render("boot"); }catch(e){ doc.innerHTML = was; }
  if (!doc.querySelector(".doclist > *")) doc.innerHTML = was;
  doc.removeAttribute("id");
}

// A page of settings on its way, in splitSects' shape: its sections' names
// and what each holds in the list, the first one picked, its heading and
// body beside the list (the template a page of settings waits as).
function skSplit(items, title, body){
  return `<div class="ssplit"><div class="rlist snav">${items.map(([t, says], j) =>
      `<button type="button" class="rrow${j ? "" : " on"}" disabled><span class="name">${esc(t)}</span><span class="rtags"><span class="dim">${esc(says)}</span></span></button>`).join("")}</div>
    <details class="sect scur" open><summary><span class="t">${esc(title)}</span></summary><div class="body"><div class="field">${body}</div></div></details></div>`;
}

// The rail's groups at the first paint: every group, inert, the one the
// address names lit; drawRail puts what this account may open in their place.
function bootRail(on){
  const item = g => `<button type="button" class="ritem${g.key === on ? " on" : ""}" disabled>${
    RAIL_ICONS[g.icon] || TOOL_ICONS[g.icon] || ""}<span class="rlbl">${esc(g.label)}</span></button>`;
  return {rail: RAIL.map(item).join(""), bar: RAIL.filter(g => RAIL_PHONE.includes(g.key)).map(item).join("")
    + `<button type="button" class="ritem" disabled>${RAIL_ICONS.more || ""}<span class="rlbl">More</span></button>`};
}

// The notebook views whose sections are always the same, by name, so the
// markup's placeholders (data-skel) and the views' own waits draw them.
const SKTPLS = {
  // As the view lands: its sections' chips, then Changes, History,
  // Branches and Claude may (Fetch, Pull and Push only come with a remote).
  git: () => skTpl(`<nav class="sectjump">${["Changes", "History", "Branches", "Claude may"].map(t => `<a href="#">${t}</a>`).join("")}</nav>`
    + [["changes", "Changes"], ["history", "History"], ["branches", "Branches"], ["may", "Claude may"]]
      .map(([k, t]) => docSection("git", k, t, "", skRows(2))).join("")
    // Shut as the view draws them until somebody opens one: CI opens only
    // when it is red, the Design view's two always start shut.
    + docSection("git", "ci", "CI", "", skRows(1), {open: false})),
  design: () => skTpl(docSection("design", "pages", "Pages", "", skRows(2), {open: false})
    + docSection("design", "themes", "Themes", "", skRows(2), {open: false})),
  // Not Version: the view draws that section itself, outside the list.
  artifacts: () => skTpl([["build", "Build", 1], ["files", "Files", 2]]
    .map(([k, t, n]) => docSection("artifacts", k, t, "", skRows(n))).join("")),
};
// A word the page needs, asked in a box in the row (R256 step 4) where
// window.prompt was: its label, the field, Cancel and OK, under the control
// that asked; Enter is OK and Escape is Cancel. Resolves with what was typed,
// trimmed, or null. One at a time: a second ask takes the first one's place.
function askInline(after, {label, value = "", ok = "OK"} = {}){
  return new Promise(resolve => {
    document.querySelectorAll(".askline").forEach(x => x.__done?.(null));
    const box = document.createElement("div");
    box.className = "field askline";
    box.innerHTML = `<label class="lbl">${esc(label)}</label><div class="askrow actbar"><input type="text" autocomplete="off" spellcheck="false" aria-label="${esc(label)}">
      <button type="button" data-askno>Cancel</button><button type="button" class="primary" data-askok>${esc(ok)}</button></div>`;
    after.insertAdjacentElement("afterend", box);
    const inp = box.querySelector("input");
    inp.value = value;
    inp.focus(); inp.select();
    const done = v => { box.remove(); resolve(v); };
    box.__done = done;
    box.querySelector("[data-askok]").onclick = () => done(inp.value.trim() || null);
    box.querySelector("[data-askno]").onclick = () => done(null);
    inp.onkeydown = e => {
      if (e.key === "Enter"){ e.preventDefault(); done(inp.value.trim() || null); }
      else if (e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); done(null); }
    };
  });
}

// A pointer to another page is a link to it (R256 step 2): the address that
// page answers at, so a press goes there as the rail does and Back returns.
const PAGE_AT = {nodes: "#/machines/nodes", docker: "#/containers", jobs: "#/jobs", toolchains: "#/build/toolchains"};
function pageLink(page, words, hash = PAGE_AT[page]){
  return `<a href="${esc(hash || "#")}" class="pagelink">${esc(words)}</a>`;
}
// A table on its way: its real head over rows whose cells shimmer, each as
// wide as its column's values tend to be.
function skTable(cols, n = 5, cls = "", rowCls = "row stack2"){
  return tblWrap(cols, Array.from({length: n}, (_, j) => `<div class="${rowCls}">${tblLine(cols, cols.map((c, i) =>
    c.act ? "" : skv(i === 0 ? 7 + (SKW[j % 8] % 5) : 2.5 + ((i + j) % 3))))}</div>`).join(""), cls);
}

function docSurface(i, kind){
  const el = $("doc" + i);
  if (!el) return null;
  if (!el.classList.contains("flush")) el.classList.add("flush");
  // Kept when this page is already drawn here (R218 step 10): built afresh on
  // every draw, a page drawn by the poll was born again each time, its list
  // fading in as if it had just arrived, its scroll and whatever was under
  // the pointer lost, though nothing in it had changed. A draw that changes
  // nothing now writes nothing: the list goes through paint(), and the bar
  // and the foot are written only when what they say moved.
  let box = el.firstElementChild;
  if (!box || el.children.length !== 1 || !box.classList.contains("doctab") || !box.classList.contains(`${kind}tab`)
      || !box.querySelector(":scope > .doclist")){
    el.innerHTML = `<div class="doctab ${esc(kind)}tab">
      <div class="field histbar docbarrow" hidden></div>
      <div class="doclist"></div>
      <div class="fnote" hidden></div>
    </div>`;
    box = el.firstElementChild;
  }
  const bar = box.querySelector(":scope > .docbarrow");
  const foot = box.querySelector(":scope > .fnote");
  const slot = (node, html) => {
    const s = String(html);
    paint(node, s, true);
    const off = !s.trim();
    if (node.hidden !== off) node.hidden = off;
  };
  // Plain nodes and two explicit setters: a slot written to becomes visible,
  // one left alone costs no empty band. (A Proxy did this implicitly at first
  // and threw Illegal invocation the moment a DOM accessor ran through it;
  // the error boundary caught it, which is the one nice thing it did.)
  return { root: box, el, bar, foot, list: box.querySelector(":scope > .doclist"),
           setBar(html){ slot(bar, html); },
           setFoot(html){ slot(foot, html); } };
}

// A section of a document tab (see "sections and action bars" in the
// stylesheet): a fold with a title, a one-line status on the right, and the
// controls inside. `kind:id` is what its open state is kept under, for this
// page's life: a fold you opened stays open across every repaint, and a
// reload starts every fold from its default: open on a desktop and shut on
// a phone, so a phone shows headings. Not stored, on purpose: a page that
// came back with last week's folds read as a page somebody else had left,
// and the sidebar's cards are the one thing here that is meant to stay as
// you arranged it. Pass `open` to override, which is for a section that IS
// the answer rather than a place to go and look for it.
const sectOpen = {};
// The attributes of a fold that remembers: its key, and `open` when it was
// left open (or, never touched, when `dflt` says so). docSection writes its
// own; this is for a fold that is not a section, a row's Details or a diff's
// file, which a redraw otherwise puts back the way it was first drawn.
function sectAttr(key, dflt = false){
  return ` data-sect="${esc(key)}"${(key in sectOpen ? sectOpen[key] : dflt) ? " open" : ""}`;
}
// Lanes for a commit graph: commits newest first, each with its parents.
// The classic walk: a commit takes the lane that was waiting for it (the
// leftmost, when several were), its first parent inherits that lane, and
// every other parent gets a lane of its own, and the edges between rows,
// for the page to draw as curves. Writes `lane` onto each commit.
function gitLanes(commits){
  const rowOf = new Map(commits.map((c, i) => [c.sha, i]));
  const lanes = [];                       // the sha each lane is waiting for
  const edges = [];
  const slot = () => { const i = lanes.indexOf(null); return i < 0 ? lanes.push(null) - 1 : i; };
  commits.forEach((c, row) => {
    const mine = lanes.map((x, i) => x === c.sha ? i : -1).filter(i => i >= 0);
    const lane = mine.length ? mine[0] : slot();
    for (const i of mine.slice(1)) lanes[i] = null;
    c.lane = lane;
    const [first, ...rest] = c.parents;
    lanes[lane] = first || null;
    for (const p of rest) if (!lanes.includes(p)) lanes[slot()] = p;
  });
  commits.forEach((c, row) => {
    for (const p of c.parents){
      const pr = rowOf.get(p);
      if (pr === undefined) continue;     // beyond what was fetched
      edges.push({from: {lane: c.lane, row}, to: {lane: commits[pr].lane, row: pr}});
    }
  });
  return {edges};
}

// A unified diff as markup: one fold per file, each line marked as added,
// removed, context or hunk head. Text only ever lands through esc().
function renderDiff(text){
  if (!text || !text.trim()) return `<div class="empty">no textual change</div>`;
  const files = [];
  let cur = null;
  for (const line of text.split("\n")){
    if (line.startsWith("diff --git ")){
      const m = /^diff --git a\/(.*) b\/(.*)$/.exec(line);
      cur = {name: m ? m[2] : line.slice(11), lines: []};
      files.push(cur);
      continue;
    }
    if (!cur){ cur = {name: "", lines: []}; files.push(cur); }
    cur.lines.push(line);
  }
  const pre = f => `<pre class="diff">${f.lines.filter(l => !/^(index |--- |\+\+\+ |new file mode|deleted file mode|similarity index|rename from|rename to|old mode|new mode)/.test(l) || !f.name)
      .map(l => `<span class="${l.startsWith("@@") ? "d-hunk" : l.startsWith("+") ? "d-add" : l.startsWith("-") ? "d-del" : "d-ctx"}">${esc(l)}\n</span>`).join("")}</pre>`;
  // A diff with no file header (a single file's, asked by path) is the
  // text alone; a fold with nothing to name would wear the browser's word.
  return files.map(f => f.name
    ? `<details class="dfile"${sectAttr("diff:" + f.name, true)}><summary><code>${esc(f.name)}</code></summary>${pre(f)}</details>`
    : pre(f)).join("");
}

// A section that has just become news (CI on main gone red) opens by itself
// once, at the moment it turns, and is the one open in its view; closed
// after that, it stays closed for as long as it stays the same news.
const sectLoud = {};
function docSection(kind, id, title, status, body, {cls = "", open, loud = false, prime = false} = {}){
  const key = `${kind}:${id}`;
  const turned = loud && !sectLoud[key];
  sectLoud[key] = loud;
  // Open unless somebody shut it, at every width (the operator, 8 Oct: too
  // much was hidden in folds).
  const isOpen = turned || (key in sectOpen ? sectOpen[key] : (open !== undefined ? open : true));
  // `prime`: the section a view is opened for (Artifacts' Files), open by
  // default beside the first on a desktop. `data-set`: its caller said open
  // or shut, which a default never overrules.
  return `<details class="sect" data-sect="${esc(key)}"${isOpen ? " open" : ""}${turned ? " data-lead" : ""}${prime ? " data-prime" : ""}${open !== undefined ? " data-set" : ""}>
    <summary><span class="t">${esc(title)}</span>${
      status ? `<span class="sst${cls ? " " + cls : ""}">${esc(status)}</span>` : ""}</summary>
    <div class="body">${body}</div>
  </details>`;
}
// ---- a page of settings: its sections a list beside the one picked ----
// The operator, 16 Oct: a page that is a run of settings sections (a
// project's Settings, Controller settings, Profile) reads as a list of them,
// each with what is in it, beside the one picked, the Roles page's shape;
// on a phone the list, then the section sliding in over it with Back, and
// the list sliding back. `root` holds the sections (details.sect) as
// children; `key` keeps which is picked; `says` is each section's line
// under its name, by its data-sect id; `marks(id)` says whether one holds
// something unsaved. Drawn again on every call, so a page that repaints
// calls it after each paint. splitOff puts the sections back one under
// another (the project's settings dialog).
const SPLIT = {};
function splitSects(root, key, {says = {}, sel = ":scope > details.sect", marks = null, back = "Back"} = {}){
  if (!root) return;
  const st = SPLIT[key] || (SPLIT[key] = {pick: "", open: false});
  root._split = {key, says, sel, marks};
  root.classList.add("ssplit");
  let nav = root.querySelector(":scope > .snav");
  if (!nav){
    nav = document.createElement("div");
    nav.className = "rlist snav";
    nav.setAttribute("role", "tablist");
    root.insertBefore(nav, root.firstChild);
    const b = document.createElement("button");
    b.type = "button"; b.className = "sback";
    b.onclick = () => { SPLIT[root._split.key].open = false; splitMove(root, "back"); splitDraw(root); };
    root.insertBefore(b, nav.nextSibling);
    root.addEventListener("input", () => splitMarks(root));
    root.addEventListener("change", () => splitMarks(root));
  }
  root.querySelector(":scope > .sback").textContent = "\u2039 " + back;
  // A section shows or hides itself as what it holds arrives (People after
  // its read): the list follows.
  root._splitObs?.disconnect();
  root._splitObs = new MutationObserver(() => splitDraw(root));
  root.querySelectorAll(sel).forEach(d => root._splitObs.observe(d, {attributes: true, attributeFilter: ["hidden"], subtree: true}));
  splitDraw(root);
}

const splitId = d => (d.dataset.sect || "").replace(/^[^:]*:/, "");

function splitDraw(root){
  const o = root._split;
  if (!o || !root.classList.contains("ssplit")) return;
  const st = SPLIT[o.key];
  // ...and not one with nothing in it to show: a settings group none of
  // whose fields is on show is drawn as nothing (.rngroup's own rule), and
  // listed it opened on an empty pane (B813).
  const empty = d => d.matches(".rngroup") && !d.querySelector(":scope > .body > .field:not([hidden]):not(.rnbarf)");
  const all = [...root.querySelectorAll(o.sel)].filter(d => !d.classList.contains("fghost")), shown = all.filter(d => !d.hidden && !empty(d));
  // The one picked, or the first shown while it is hidden (its list being
  // read again), without forgetting it: it comes back when it shows.
  let pick = st.pick;
  if (!shown.some(d => splitId(d) === pick)) pick = shown[0] ? splitId(shown[0]) : "";
  const nav = root.querySelector(":scope > .snav");
  const html = shown.map(d => { const k = splitId(d), on = k === pick;
    const say = o.says[k] ?? d.querySelector(":scope > summary .sst")?.textContent ?? "";
    return `<button type="button" class="rrow${on ? " on" : ""}" role="tab" aria-selected="${on}" data-spick="${esc(k)}">
      <span class="name">${esc(d.querySelector(":scope > summary .t")?.textContent || k)}</span>
      <span class="rtags">${say ? `<span class="dim">${esc(say)}</span>` : ""}<span class="sunsaved" hidden>unsaved</span></span></button>`; }).join("");
  if (nav.dataset.drawn !== html){
    nav.innerHTML = html; nav.dataset.drawn = html;
    nav.querySelectorAll("[data-spick]").forEach(b => b.onclick = () => {
      st.pick = b.dataset.spick; st.open = true;
      // At a desk the section fades through, as a rail page does; on a
      // phone it slides in over the list.
      splitAway(() => [...root.querySelectorAll(o.sel)].filter(d => d.classList.contains("scur")),
                () => { splitMove(root, "in"); splitDraw(root); });
      if (matchMedia("(max-width: 900px)").matches) root.scrollIntoView?.({block: "start"});
    });
  }
  all.forEach(d => { const on = splitId(d) === pick;
    if (d.classList.contains("scur") !== on) d.classList.toggle("scur", on);
    if (on && !d.open) d.open = true; });
  root.classList.toggle("sopen", st.open);
  splitMarks(root);
}

// A pick on a list beside its detail: a fade through at a desk (fadeThrough),
// and on a phone the redraw alone, which plays its slide (splitMove).
function splitAway(parts, swap){
  return matchMedia("(max-width: 900px)").matches ? swap() : fadeThrough(parts, swap);
}

// The phone's slide: in from the right to a section, back from the left to
// the list, restarted on each press.
function splitMove(root, how){
  delete root.dataset.move;
  void root.offsetWidth;
  root.dataset.move = how;
  // Taken off once it has run: a page that repaints (Controller settings on
  // the poll) would play it again on every paint.
  clearTimeout(root._splitT);
  root._splitT = setTimeout(() => { delete root.dataset.move; }, 320);
}

function splitMarks(root){
  const o = root._split;
  if (!o?.marks) return;
  root.querySelectorAll(":scope > .snav [data-spick]").forEach(b => {
    let dirty = false;
    try { dirty = !!o.marks(b.dataset.spick); } catch { /* a form not drawn yet */ }
    const m = b.querySelector(".sunsaved");
    if (m && m.hidden === dirty) m.hidden = !dirty;
  });
}

function splitOff(root){
  if (!root?.classList.contains("ssplit")) return;
  root.classList.remove("ssplit", "sopen");
  root.querySelectorAll(":scope > details.sect").forEach(d => d.classList.remove("scur"));
}

function wireSections(root){
  root.querySelectorAll("details.sect").forEach(d => {
    // Its state is recorded by the page's one toggle listener, beside
    // sectAttr, and only for a fold that has a key: one without keeps its
    // own (the Git view's file and branch folds do, by path and by name).
    // Driven, not the browser's instant snap: the same helper the memories,
    // the bug reports, the version tab's fold and the Docker manager's wiring
    // fold already use. A <details> opens at full height by construction, so
    // a fold on this page only moves if something moves it, and sections
    // shipped without it: the one kind of fold that jumped.
    //
    // `:scope > summary` because a section can contain folds of its own, and
    // the section must not answer for theirs.
    const sum = d.querySelector(":scope > summary");
    if (sum) sum.onclick = e => { e.preventDefault(); if (!d.open) soleOpen(d); slideDetails(d, !d.open); };
  });
  const view = root.closest?.(".nbview, .doctab") || root.querySelector?.(".doctab");
  if (view){
    oneOpen(view);
    root.querySelectorAll("details.sect").forEach(oneOpen);
    sectJump(view);
  }
}
// A jump bar over a long surface (the operator, 8 Oct): with every section
// open, the names of the sections in a line at the top, each scrolling to
// its own and opening it if somebody shut it. Four or more sections make
// a surface long enough to want one; a surface with fewer has none.
function sectJump(g){
  // A surface's own sections, which each have a title of their own: a fold
  // repeated once per row of a list (the Docker tab's Ports and mounts, one
  // per container) is the row's, and seventeen of them made a bar of
  // seventeen links all called the same (the operator, 8 Oct).
  const titleOf = o => o.querySelector(":scope > summary .t")?.textContent || "";
  const all = sectsOf(g), seen = {};
  all.forEach(o => { seen[titleOf(o)] = (seen[titleOf(o)] || 0) + 1; });
  const mine = all.filter(o => seen[titleOf(o)] === 1);
  const have = g.querySelector(":scope .sectjump");
  if (mine.length < 4){ have?.remove(); return; }
  const bar = have || document.createElement("nav");
  // In a dialog every line is a .field band (the design's dialog layout).
  bar.className = g.matches("[data-sects]") ? "field sectjump" : "sectjump";
  bar.setAttribute("aria-label", "sections");
  bar.innerHTML = mine.map(o => `<a href="#" data-jump="${esc(o.dataset.sect || "")}">${
    esc(titleOf(o))}</a>`).join("");
  if (!have) mine[0].before(bar);
  bar.querySelectorAll("[data-jump]").forEach(a => a.onclick = e => {
    e.preventDefault();
    const d = mine.find(o => (o.dataset.sect || "") === a.dataset.jump);
    if (!d) return;
    if (!d.open){ d.open = true; if (d.dataset.sect) sectOpen[d.dataset.sect] = true; }
    d.scrollIntoView({block: "start", behavior: "smooth"});
  });
}
// Every section is open by default at a desk and several stand open there
// (the operator, 8 Oct: too much was hidden in folds); a long surface has a
// jump bar (sectJump). On a phone one section is open at a time on every
// folded surface, as the notebook's views do: opening one shuts the others
// (the operator, 11 Oct, R184), so the page is never a stack of open folds
// to scroll. Among siblings only: a section's own folds (a page's rules
// inside Pages) take turns among themselves and never close the section
// holding them.
const sectLast = new WeakMap();     // a group -> the key of the section last opened in it
// ...and the same by the group's NAME (the sections' key prefix, "nodes" for
// nodes:health and the rest): a redraw between a press and the next draw
// replaces the group's element, and a WeakMap keyed on the old one forgot
// the press, so the draw opened the prime section instead (B723).
const sectLastByName = new Map();
const sectGroupName = g => (sectsOf(g)[0]?.dataset.sect || "").split(":")[0] || "";
function sectRemember(g, key){
  sectLast.set(g, key);
  const n = sectGroupName(g);
  if (n) sectLastByName.set(n, key);
}
function sectRecall(g){
  const have = sectLast.get(g);
  if (have !== undefined) return have;
  const n = sectGroupName(g);
  return n ? sectLastByName.get(n) : undefined;
}
// A group is a view, a tab, a fold holding folds, or a dialog box that says
// it holds sections (`data-sects`: the project settings, the operator 7 Oct).
function sectGroup(d){ return d.parentElement?.closest("details.sect, .nbview, .doctab, [data-sects]") || null; }
const sectRuled = g => !!g?.closest?.(".nb, .doctab, [data-sects]");
// Its sections in the order drawn, those a person can see: a settings group
// with nothing in it is display:none and is no group's first.
const sectsOf = g => [...g.querySelectorAll("details.sect")]
  .filter(o => sectGroup(o) === g && getComputedStyle(o).display !== "none");
// Nobody has opened or shut it, and its caller left it to the default.
const sectDefault = o => !(o.dataset.sect && o.dataset.sect in sectOpen) && !o.hasAttribute("data-set");
function soleOpen(d){
  const g = sectGroup(d);
  if (!sectRuled(g)) return;
  sectRemember(g, d.dataset.sect || "");
  // Recorded now, not when the slide ends: a repaint landing mid-slide read
  // the one sliding shut as still open and kept it over the one just opened.
  if (d.dataset.sect) sectOpen[d.dataset.sect] = true;
  // On a phone the others shut as this one opens (R184); a desk keeps them.
  // Shut by the rule, not by a hand: nothing is recorded for them, so a desk
  // this page is widened to shows them open again as it always did, and the
  // press mark comes off so the toggle their slide fires records nothing.
  if (!isPhone()) return;
  for (const o of sectsOf(g)){
    if (o === d || !o.open) continue;
    delete o.dataset.pressed;
    slideDetails(o, false);
  }
}
// A section opened by a draw rather than by a hand (Memories, remembered
// open): it is the one that stays, and on a phone the others shut at once,
// since a slide here overlapped two sections for its length (uniform, 6 Oct).
function keepOpen(d){
  const g = sectGroup(d);
  if (!sectRuled(g)) return;
  sectRemember(g, d.dataset.sect || "");
  oneOpen(g);
}
// After a draw. At a desk nothing anybody chose is moved: every section
// stands open unless somebody shut it. On a phone one stands open: the one
// last opened by a hand or a draw, else the one the view is for (prime),
// else the first; the rest are shut without a slide, since a draw is not a
// press (R184).
function oneOpen(g){
  if (!sectRuled(g)) return;
  const mine = sectsOf(g);
  for (const o of mine){
    if (o.hasAttribute("data-lead")){ o.removeAttribute("data-lead"); sectRemember(g, o.dataset.sect || ""); continue; }
    // Open unless somebody shut it, at a desk (the operator, 8 Oct).
    if (sectDefault(o)) o.open = true;
  }
  if (!isPhone() || mine.length < 2) return;
  const last = sectRecall(g);
  const keep = mine.find(o => last && (o.dataset.sect || "") === last)
    || mine.find(o => o.hasAttribute("data-prime"))
    || mine.find(o => o.open) || mine[0];
  for (const o of mine) o.open = o === keep;
}
// A button that is doing something says so until the repaint replaces it:
// grayed, and wearing the verb with an animated ellipsis. Pair with
// pressing(): that disables for the round trip, this says what for.
// An action bar's More (R210): the primary verbs stay on the bar and the
// rest go behind one button, whose menu opens under it. `items` are the
// bar's own button strings in their order, destructive last; an empty one is
// skipped, a single leftover is drawn inline (a menu of one is a detour),
// and two or more make the menu. wireMore() wires the button; the page's
// one click listener (index.html) shuts every open menu.
function actMore(items){
  const have = items.filter(Boolean);
  if (have.length < 2) return have.join("");
  // ⋯, as a project's header has it (the operator, 17 Oct): the rest of a
  // row's verbs behind one small press, named for a screen reader.
  return `<span class="more"><button type="button" class="moreb" aria-haspopup="menu" aria-expanded="false" aria-label="More"
      title="the rest of what can be done to it">⋯</button>
    <div class="actmenu" hidden role="menu">${have.join("")}</div></span>`;
}
function wireMore(root){
  root.querySelectorAll(".actbar .more > button").forEach(b => b.onclick = () => {
    const m = b.nextElementSibling;
    const open = m.hidden;
    closeMore();
    if (open){ m.hidden = false; b.setAttribute("aria-expanded", "true"); }
  });
}
function closeMore(){
  document.querySelectorAll(".actmenu:not([hidden])").forEach(m => {
    m.hidden = true;
    m.previousElementSibling?.setAttribute("aria-expanded", "false");
  });
}

function busy(btn, word){
  if (!btn) return;
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  btn.innerHTML = `${esc(word)}<span class="dots"></span>`;
  // The one ticker every .dots on the page shares; it stops itself when
  // the last one is repainted away.
  if (!tcDotsTimer) tcDotsTimer = setInterval(tcTickDots, 400);
}

// ...and the other half, for a press that can fail without a repaint behind
// it. Most busy() calls need none: the round trip redraws the surface and
// the button with it, but the notebook's Send and Save both stay on screen
// when the server says no, and a button left wearing "Sending…" over a
// refusal is the worst of both.
function unbusy(btn, word){
  if (!btn) return;
  btn.disabled = false;
  btn.removeAttribute("aria-busy");
  btn.textContent = word;
}

// ---- tiles, facts, tables, charts and chips (R216, R218, the 2.0 language)
// Three shapes every document tab draws the same way, held by the design's
// rules tiles, facts and chips and measured by uniform.mjs.

// A page's status line (the operator, 17 Oct: one order for every page's
// top): under the tiles, when its things were last checked or what state
// they are in at the left, its upkeep actions (Check for updates, Measure
// now, Install selected) at the right, on one line. `said` is markup; `cls`
// names the page's own line for its wiring and its suites.
function headLine(said, actions = "", cls = ""){
  if (!said && !actions) return "";
  return `<div class="field headline${cls ? " " + esc(cls) : ""}"><div class="actbar"><span class="state">${said}</span>${actions}</div></div>`;
}

// A row of tiles under a tab's bar: each a number the tab is about, with
// its label under it and, when the number itself is news, a tone. Facts
// to look at, never pressed; a tile for a number that is always the same
// is not drawn, which is what the `omit` flag is for.
function statTiles(tiles){
  const rows = (tiles || []).filter(t => t && !t.omit);
  if (!rows.length) return "";
  return `<div class="field"><div class="tiles">${rows.map(t => `
    <div class="tile${t.tone ? " " + esc(t.tone) : ""}"${t.title ? ` title="${esc(t.title)}"` : ""}>
      <div class="tv">${esc(String(t.value ?? "–"))}${t.unit ? `<span class="tu">${esc(t.unit)}</span>` : ""}</div>
      <div class="tl">${esc(t.label || "")}</div>
      ${t.sub ? `<div class="ts">${esc(t.sub)}</div>` : ""}
    </div>`).join("")}</div></div>`;
}

// What a row knows, as labels and values: two columns at a desk, one on a
// phone. A pair whose value is empty is left out, so a caller lists what
// it has and the grid says what there is. `html` on a pair means the value
// is already markup (a code span, a link); otherwise it is escaped, and
// `cls` names the value's element for a suite that reads one.
// What a card's settings are, read (the operator's concept, 17 Oct): one
// wrapping line of pills, each its label in the quiet voice and its value,
// a pill with no label a state on its own (Starts on boot); `edit` is the
// button that swaps the fields in, at the line's right (rows-you-open),
// wearing the pencil the Commands panel's edit wears (PENCIL).
function factPills(pairs, edit = "", cls = ""){
  const rows = (pairs || []).filter(p => p && String(p[1] ?? "").trim() !== "");
  if (!rows.length && !edit) return "";
  return `<div class="fpills${cls ? " " + esc(cls) : ""}"><div class="fpl">${rows.map(([k, v, tone]) =>
    `<span class="fpill${tone ? " " + esc(tone) : ""}">${k ? `<span class="k">${esc(k)}</span>` : ""}<span class="v">${v}</span></span>`).join("")}</div>${
    edit}</div>`;
}

function factGrid(pairs, cls = ""){
  const rows = (pairs || []).filter(p => p && p[1] !== undefined && p[1] !== null && String(p[1]).trim() !== "");
  if (!rows.length) return "";
  return `<dl class="facts${cls ? " " + esc(cls) : ""}">${rows.map(([k, v, opt]) => `
    <div class="fact"><dt>${esc(k)}</dt><dd${opt && opt.cls ? ` class="${esc(opt.cls)}"` : ""}>${opt && opt.html ? v : esc(String(v))}</dd></div>`).join("")}</dl>`;
}

// ---- tables (R218 step 8, the design's tables rule) -----------------------
// A list whose rows are all the same shape is a table: a header line naming
// the columns over rows whose first line holds the same columns, so a value
// is found by looking down a column rather than by reading every row. Each
// row is still a row: a reason under its line in red, its buttons at the
// line's right end, what is long (a log, a card) behind its fold. On a phone
// the header goes and each cell after the first wears its column's name.
//
// `cols` is [{label, w, num, act}]: `w` a grid track, a share (the default,
// minmax(0,1fr)) or a fixed width and never auto, since each line is its own
// grid and only shares and widths line up across them; `num` right-aligns
// tabular figures; `act` is the buttons' column, unlabeled.
function tblTracks(cols){
  return cols.map(c => c.w || "minmax(0,1fr)").join(" ");
}
// The table around its rows, the header line first.
function tblWrap(cols, rows, cls = ""){
  return `<div class="tbl${cls ? " " + esc(cls) : ""}" style="--tcols:${tblTracks(cols)}">
    <div class="thead">${cols.map(c => `<span class="th${c.num ? " num" : ""}${c.act ? " act" : ""}">${
      c.act ? "" : esc(c.label || "")}</span>`).join("")}</div>${rows}</div>`;
}
// One row's line: a cell per column, in order; a cell is markup already.
// `tag` is "summary" for a row whose line opens its fold, `cls` its own
// class, `attrs` its own attributes (a data- key a wiring reads).
function tblLine(cols, cells, tag = "div", cls = "", attrs = ""){
  return `<${tag} class="tline${cls ? " " + esc(cls) : ""}"${attrs ? " " + attrs : ""}>${cols.map((c, i) => `<span class="td${i === 0 ? " lead" : ""}${
    c.num ? " num" : ""}${c.act ? " act" : ""}"${i && !c.act && c.label ? ` data-th="${esc(c.label)}"` : ""}>${cells[i] ?? ""}</span>`).join("")}</${tag}>`;
}

// ---- charts (R218 step 9, the design's charts rule) -----------------------
// Where a number moves: an hour's line chart on a node's page and a
// sparkline beside a running container's number, drawn inline with no
// library. One series to a chart, so no legend: the caption names it. The
// plot is an SVG stretched to its box with strokes that do not scale; the
// axis labels and the end dot are HTML, so text keeps its size at every
// width. A gap longer than three samples' spacing breaks the line rather
// than drawing across a time nobody measured.

// A sparkline: the values in the quiet voice, the last one a dot in the
// accent, 96 by 24. `max` is the scale's top (100 for a percentage, more
// when a container's CPU spans cores).
function sparkSvg(vals, max = 100, label = ""){
  const v = (vals || []).filter(x => typeof x === "number");
  if (v.length < 2) return "";
  const top = Math.max(max, ...v), W = 96, H = 24, pad = 3;
  const pt = (x, i) => [pad + i * (W - 2 * pad) / (v.length - 1), H - pad - x / top * (H - 2 * pad)];
  const pts = v.map(pt), last = pts.at(-1);
  return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">
    <polyline points="${pts.map(p => p.map(n => n.toFixed(1)).join(",")).join(" ")}"/>
    <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3"/></svg>`;
}

// The hour as a chart: `pts` is [[at, value], ...], `fmt` how a value is
// said, `max` the scale's top. Its id keeps the crosshair where it was
// across the redraw a new sample brings.
const CHART_SPAN = 3600;
function hourChart(id, title, pts, fmt = v => `${Math.round(v)}%`, max = 100){
  const p = (pts || []).filter(x => x && typeof x[1] === "number");
  if (!p.length) return `<figure class="chart" data-chart="${esc(id)}"><figcaption><span class="ct">${esc(title)}</span></figcaption>
    <div class="hint">no samples yet: the node sends one each poll</div></figure>`;
  const now = p.at(-1)[0], from = now - CHART_SPAN, vals = p.map(x => x[1]);
  const top = Math.max(max, ...vals);
  const X = at => Math.max(0, Math.min(1000, (at - from) / CHART_SPAN * 1000)), Y = v => 100 - v / top * 100;
  // Runs split where the samples stop: a node that went quiet is a gap, not
  // a slope. Measured against the slow end of its spacing, not the middle:
  // a busy node reports in bursts seconds apart and an idle one at the
  // poll, so three of the median broke every idle stretch, which is where
  // the load sits low, into dots (the operator, 16 Oct).
  const gaps = p.slice(1).map((x, i) => x[0] - p[i][0]).sort((a, b) => a - b);
  const slow = gaps.length ? gaps[Math.min(gaps.length - 1, Math.floor(gaps.length * 0.9))] : 60;
  const runs = [[p[0]]];
  for (let i = 1; i < p.length; i++){
    if (p[i][0] - p[i - 1][0] > Math.max(slow * 3, 90)) runs.push([]);
    runs.at(-1).push(p[i]);
  }
  const line = runs.map(r => r.map((x, i) => `${i ? "L" : "M"}${X(x[0]).toFixed(1)},${Y(x[1]).toFixed(1)}`).join("")).join("");
  const fill = runs.filter(r => r.length > 1).map(r => `M${X(r[0][0]).toFixed(1)},100${
    r.map(x => `L${X(x[0]).toFixed(1)},${Y(x[1]).toFixed(1)}`).join("")}L${X(r.at(-1)[0]).toFixed(1)},100Z`).join("");
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length, last = p.at(-1);
  return `<figure class="chart" data-chart="${esc(id)}">
    <figcaption><span class="ct">${esc(title)}</span><span class="cv">${esc(fmt(last[1]))}</span>
      <span class="cs">the last hour: low ${esc(fmt(Math.min(...vals)))}, average ${esc(fmt(avg))}, high ${esc(fmt(Math.max(...vals)))}</span></figcaption>
    <div class="cplot">
      <div class="cy" aria-hidden="true"><span>${esc(fmt(top))}</span><span>${esc(fmt(top / 2))}</span><span>${esc(fmt(0))}</span></div>
      <div class="carea" tabindex="0" role="img" aria-label="${esc(`${title} over the last hour, now ${fmt(last[1])}`)}"
        data-pts="${esc(JSON.stringify(p.map(x => [x[0], x[1]])))}" data-from="${from}">
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
          <line class="cgrid" x1="0" x2="1000" y1="0" y2="0"/><line class="cgrid" x1="0" x2="1000" y1="50" y2="50"/>
          <line class="cgrid" x1="0" x2="1000" y1="100" y2="100"/>
          <path class="cfill" d="${fill}"/><path class="cline" d="${line}"/></svg>
        <span class="cdot" style="left:${(X(last[0]) / 10).toFixed(2)}%;top:${Y(last[1]).toFixed(2)}%"></span>
        <span class="chair" hidden></span><span class="ctip" hidden></span>
        <div class="cx" aria-hidden="true"><span>an hour ago</span><span>30 min</span><span>now</span></div>
      </div>
    </div></figure>`;
}

// The crosshair: it finds the nearest sample to the pointer (or, focused,
// the one the arrow keys move to) and says its value and its time. Kept by
// chart id across a redraw, until the pointer leaves.
let chartHover = {id: "", i: -1};
function wireCharts(root, fmtOf = () => v => `${Math.round(v)}%`){
  root.querySelectorAll(".chart .carea").forEach(a => {
    const fig = a.closest(".chart"), id = fig.dataset.chart, fmt = fmtOf(id);
    let pts;
    try{ pts = JSON.parse(a.dataset.pts || "[]"); }catch(e){ pts = []; }
    if (!pts.length) return;
    const from = Number(a.dataset.from), hair = a.querySelector(".chair"), tip = a.querySelector(".ctip");
    const show = i => {
      if (i < 0){ hair.hidden = tip.hidden = true; return; }
      const x = Math.max(0, Math.min(100, (pts[i][0] - from) / CHART_SPAN * 100));
      hair.style.left = tip.style.left = `${x}%`;
      tip.classList.toggle("flip", x > 70);
      tip.textContent = "";
      const b = document.createElement("b"); b.textContent = fmt(pts[i][1]);
      tip.append(b, " ", new Date(pts[i][0] * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}));
      hair.hidden = tip.hidden = false;
      chartHover = {id, i};
    };
    const near = ev => {
      const r = a.getBoundingClientRect(), at = from + (ev.clientX - r.left) / r.width * CHART_SPAN;
      let best = 0;
      pts.forEach((p, i) => { if (Math.abs(p[0] - at) < Math.abs(pts[best][0] - at)) best = i; });
      return best;
    };
    a.onpointermove = ev => show(near(ev));
    a.onpointerleave = () => { if (document.activeElement !== a){ show(-1); chartHover = {id: "", i: -1}; } };
    a.onfocus = () => show(chartHover.id === id && chartHover.i >= 0 ? Math.min(chartHover.i, pts.length - 1) : pts.length - 1);
    a.onblur = () => { show(-1); chartHover = {id: "", i: -1}; };
    a.onkeydown = ev => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      const i = chartHover.id === id ? chartHover.i : pts.length - 1;
      show(Math.max(0, Math.min(pts.length - 1, i + (ev.key === "ArrowLeft" ? -1 : 1))));
    };
    if (chartHover.id === id && chartHover.i >= 0) show(Math.min(chartHover.i, pts.length - 1));
  });
}

// A row of chips narrowing a list: All first, then one per group with its
// count, the one in force wearing `.on`. A chip is a view, never a setting:
// the caller keeps which is on for the page's life and nothing is saved.
// `groups` is [{key, label, count}], `on` the key in force ("" for All).
function chipBar(groups, on, attr){
  const chips = chipButtons(groups, on, attr);
  return chips ? `<div class="field"><div class="chips">${chips}</div></div>` : "";
}
// The chips alone, for a band that holds more than them (a list's search
// beside them, R254 step 1): "" when fewer than two groups have anything.
function chipButtons(groups, on, attr){
  const gs = (groups || []).filter(g => g && g.count);
  if (gs.length < 2) return "";
  const total = gs.reduce((n, g) => n + g.count, 0);
  const chip = (key, label, count) => `<button type="button" class="chip${(on || "") === key ? " on" : ""}"
    ${attr}="${esc(key)}" aria-pressed="${(on || "") === key}">${esc(label)}<span class="pill">${count}</span></button>`;
  return chip("", "All", total) + gs.map(g => chip(g.key, g.label, g.count)).join("");
}
