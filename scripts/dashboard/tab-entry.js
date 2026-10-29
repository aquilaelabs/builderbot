"use strict";
// A Library entry's own page (R183, the operator, 29 Oct: view details opens
// into a page with a back button): Details on a Library card opens that
// catalog entry's page on the node picked, a page a press opens, with the
// small top header's Back to where it was opened from. Its head is the
// card's (its glyph or its own icon, its name, its pills, where it stands and
// its one verb), its body what the card's Details held across the grid: the
// catalog's entry alone, never a sign-in or a node's lines, which are an
// installed thing's page's.

let entryKey = "";   // KIND:NAME on show, on libNode

// Open one Library entry's page on a node.
function openEntry(node, key){
  if (node && node !== libNode){ libNode = node; lib = null; }
  entryKey = key;
  // Its own address, and where it was opened from kept before it draws (Back).
  const was = location.hash;
  const to = `#/build/library/${encodeURIComponent(libNode || "")}/${encodeURIComponent(entryKey)}`;
  shellCame(was, to);
  openTab({kind: "entry", arg: "__entry", label: "Library"});
  libRev++;
  if (to !== was) shellPush(to, was);
  // Read afresh, as opening the Library is: a press is somebody asking now.
  loadLibrary();
}

function entryRow(){
  return (lib?.rows || []).find(r => `${r.kind}:${r.name}` === entryKey) || null;
}
function entryLabel(){ return entryRow()?.label || entryKey.split(":").slice(1).join(":") || "Library"; }

function renderEntryInto(i){
  const d = docSurface(i, "entry");
  if (!d) return;
  d.setBar("");
  if (lib === null){
    d.list.innerHTML = skTpl(pageHead({title: GHOST, facts: [["Node", GHOST]]}) + docSection("entry", "about", "What it is", "", skRows(3)));
    if (!libSeq) loadLibrary();
    return;
  }
  const r = entryRow();
  if (lib.error || !r){
    paint(d.list, `<div class="field"><div class="notice ${lib.error ? "bad" : "warn"}">${esc(lib.error
      ? "could not read the Library: " + lib.error
      : `${entryLabel()} is not in the Library for ${lib.name || "this node"} now.`)}</div></div>`);
    return;
  }
  const may = lib.may || {};
  const head = pageHead({title: r.label, pills: `${libPills(r)} ${libState(r)}`, facts: [["Node", lib.name || ""]],
    actions: `<span class="actbar">${libActs(r, may)}</span>`, cls: "entryhead"});
  const err = !r.running && (r.kind === "toolchain" || r.kind === "pack") && lib?.job?.errors?.[r.name] ? `<div class="field"><div class="sub bad">${esc(lib.job.errors[r.name])}</div></div>` : "";
  const about = `${r.about ? `<span class="sub">${esc(r.about)}</span>` : ""}${r.machine && r.name === TC_DRIVER ? libDriverPick(r.machine) : ""}${libDetail(r)}`;
  paint(d.list, `<div data-libnode="${esc(libNode)}" data-entry="${esc(entryKey)}"><div class="field entryicon">${libIcon(r)}</div>${head}${err}${
    docSection("entry", "about", "What it is", "", `<div class="field ldetail">${about}</div>`, {open: true})}</div>`);
  wireLibrary(d.el);
}
