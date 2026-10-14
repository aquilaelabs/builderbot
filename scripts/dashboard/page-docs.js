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

function docSurface(i, kind){
  const el = $("doc" + i);
  if (!el) return null;
  el.classList.add("flush");
  el.innerHTML = `<div class="doctab ${esc(kind)}tab">
    <div class="field histbar docbarrow" hidden></div>
    <div class="doclist"></div>
    <div class="fnote" hidden></div>
  </div>`;
  const box = el.firstElementChild;
  const bar = box.querySelector(".docbarrow");
  const foot = box.querySelector(".fnote");
  // Plain nodes and two explicit setters: a slot written to becomes visible,
  // one left alone costs no empty band. (A Proxy did this implicitly at first
  // and threw Illegal invocation the moment a DOM accessor ran through it;
  // the error boundary caught it, which is the one nice thing it did.)
  return { root: box, el, bar, foot, list: box.querySelector(".doclist"),
           setBar(html){ bar.innerHTML = html; bar.hidden = !String(html).trim(); },
           setFoot(html){ foot.innerHTML = html; foot.hidden = !String(html).trim(); } };
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
  return `<span class="more"><button type="button" aria-haspopup="menu" aria-expanded="false"
      title="the rest of what can be done to it">More</button>
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

// ---- tiles, facts and chips (R216, the 2.0 language) ----------------------
// Three shapes every document tab draws the same way, held by the design's
// rules tiles, facts and chips and measured by uniform.mjs.

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
function factGrid(pairs, cls = ""){
  const rows = (pairs || []).filter(p => p && p[1] !== undefined && p[1] !== null && String(p[1]).trim() !== "");
  if (!rows.length) return "";
  return `<dl class="facts${cls ? " " + esc(cls) : ""}">${rows.map(([k, v, opt]) => `
    <div class="fact"><dt>${esc(k)}</dt><dd${opt && opt.cls ? ` class="${esc(opt.cls)}"` : ""}>${opt && opt.html ? v : esc(String(v))}</dd></div>`).join("")}</dl>`;
}

// A row of chips narrowing a list: All first, then one per group with its
// count, the one in force wearing `.on`. A chip is a view, never a setting:
// the caller keeps which is on for the page's life and nothing is saved.
// `groups` is [{key, label, count}], `on` the key in force ("" for All).
function chipBar(groups, on, attr){
  const gs = (groups || []).filter(g => g && g.count);
  if (gs.length < 2) return "";
  const total = gs.reduce((n, g) => n + g.count, 0);
  const chip = (key, label, count) => `<button type="button" class="chip${(on || "") === key ? " on" : ""}"
    ${attr}="${esc(key)}" aria-pressed="${(on || "") === key}">${esc(label)}<span class="pill">${count}</span></button>`;
  return `<div class="field"><div class="chips">${chip("", "All", total)}${
    gs.map(g => chip(g.key, g.label, g.count)).join("")}</div></div>`;
}
