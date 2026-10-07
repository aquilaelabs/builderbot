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
  const isOpen = turned || (key in sectOpen ? sectOpen[key] : (open !== undefined ? open : !isPhone()));
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
  }
}
// The first section of a group is open by default, and on a phone one
// section is open at a time; on a desktop several may stand open (the
// operator, 7 Oct). One at a time had come in on 5 and 6 Oct for every
// width, because several open on a phone made a surface a long scroll and
// the section being worked in was hard to keep hold of; a desktop has the
// room, and shutting one section to read another there was a step for
// nothing. Among siblings only: a section's own folds (a page's rules
// inside Pages) take turns among themselves and never close the section
// holding them.
const sectLast = new WeakMap();     // a group -> the key of the section last opened in it
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
  sectLast.set(g, d.dataset.sect || "");
  // Recorded now, not when the slide ends: a repaint landing mid-slide read
  // the one sliding shut as still open and kept it over the one just opened.
  if (d.dataset.sect) sectOpen[d.dataset.sect] = true;
  if (!isPhone()) return;
  g.querySelectorAll("details.sect[open]").forEach(o => {
    if (o === d || sectGroup(o) !== g) return;
    if (o.dataset.sect) sectOpen[o.dataset.sect] = false;
    slideDetails(o, false);
  });
}
// A section opened by a draw rather than by a hand (Memories, remembered
// open): it is the one that stays, and on a phone the others shut at once,
// since a slide here overlapped two sections for its length (uniform, 6 Oct).
function keepOpen(d){
  const g = sectGroup(d);
  if (!sectRuled(g)) return;
  sectLast.set(g, d.dataset.sect || "");
  oneOpen(g);
}
// After a draw. Nothing anybody chose is moved: the first section stands
// open unless somebody shut it, and on a desktop the view's own (`prime`,
// Artifacts' Files) with it, every other default shut. On a phone, if more
// than one is open, the one last opened stays, else one the person opened
// before, else the first; the rest shut at once, without the slide, since
// nothing moved them.
function oneOpen(g){
  if (!sectRuled(g)) return;
  const mine = sectsOf(g);
  if (!mine.length) return;
  const first = mine[0];
  if (!isPhone()){
    for (const o of mine){
      if (o.hasAttribute("data-lead")){ o.removeAttribute("data-lead"); sectLast.set(g, o.dataset.sect || ""); continue; }
      if (sectDefault(o)) o.open = o === first || o.hasAttribute("data-prime");
    }
    return;
  }
  const open = mine.filter(o => o.open);
  if (!open.length){
    if (sectDefault(first) || sectOpen[first.dataset.sect] === true) first.open = true;
    return;
  }
  if (open.length < 2) return;
  const keep = open.find(o => o.hasAttribute("data-lead"))
    || open.find(o => o.dataset.sect && o.dataset.sect === sectLast.get(g))
    || open.find(o => o.dataset.sect && sectOpen[o.dataset.sect] === true)
    || (open.includes(first) && first) || open[0];
  if (keep.hasAttribute("data-lead")){ keep.removeAttribute("data-lead"); sectLast.set(g, keep.dataset.sect || ""); }
  open.forEach(o => { if (o !== keep){ o.open = false; if (o.dataset.sect) sectOpen[o.dataset.sect] = false; } });
}
// A button that is doing something says so until the repaint replaces it:
// grayed, and wearing the verb with an animated ellipsis. Pair with
// pressing(): that disables for the round trip, this says what for.
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
