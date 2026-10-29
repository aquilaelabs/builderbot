"use strict";
// An installed thing's own page (R181 step 2, the operator, 29 Oct): a coding
// agent, a toolchain, a tool pack or a service on one node, opened by Open or
// Configure on its Installed row (or Configure on the router's container),
// never by a tab of its own. A page a press opens: the small top header with
// Back, then the thing's head (its name, its version, where it stands, its
// verbs) and its sections, each drawn from THING_SECTS by its kind.
//
// THING_SECTS is the one table a later plugin system would add a pack's own
// sections to from its manifest (step 3); nothing a manifest says draws
// markup until that is designed.

let thingKey = "";   // KIND:NAME on show, on instNode

// Open one thing's page on a node, at its Configure section when asked.
function openThing(node, key, at = ""){
  if (node && node !== instNode){ instNode = node; inst = null; }
  thingKey = key;
  if (at) thingAt = at;
  // Its own address, and where it was opened from kept before it draws, so
  // its top header names that page on the first paint (Back).
  const was = location.hash;
  const to = `#/machines/installed/${encodeURIComponent(instNode || "")}/${encodeURIComponent(thingKey)}`;
  shellCame(was, to);
  openTab({kind: "thing", arg: "__thing", label: "Installed"});
  instRev++;
  if (to !== was) shellPush(to, was);
  // Read afresh, as opening Installed is: a press is somebody asking now.
  loadInstalled();
}
let thingAt = "";    // a section to open on once drawn (configure)

function thingRow(){
  return (inst?.rows || []).find(r => `${r.kind}:${r.name}` === thingKey) || null;
}
function thingLabel(){ return thingRow()?.label || thingKey.split(":").slice(1).join(":") || "Installed"; }

// Each kind's sections: [key, title, the body for its row or ""]. A section
// with nothing to say is not drawn.
const THING_SECTS = {
  agent: [
    ["about", "What it is", r => instAboutLines(r)],
    ["signin", "Your sign-in", r => {
      const n = (nodesList || []).find(x => x.id === instNode), a = agentById(r.agent);
      return n && (r.installed || r.agent === "claude") && typeof signinBlock === "function" && a?.provider ? signinBlock(n, r.agent) : "";
    }],
    ["yours", "Yours", r => { const a = agentById(r.agent); return r.installed && a ? agExtras(a) : ""; }],
  ],
  toolchain: [
    ["about", "What it is", r => instAboutLines(r)],
    ["configure", "Configure", r => instConfigLines(r)],
  ],
  pack: [
    ["about", "What it is", r => instAboutLines(r)],
    ["configure", "Configure", r => instConfigLines(r)],
  ],
  service: [
    ["about", "What it is", r => instServiceLines(r)],
    ["configure", "Configure", r => instConfigForm(r)],
  ],
};

function renderThingInto(i){
  const d = docSurface(i, "thing");
  if (!d) return;
  d.setBar("");
  if (inst === null){
    d.list.innerHTML = skTpl(pageHead({title: GHOST, facts: [["Installed", GHOST]]}) + docSection("thing", "about", "What it is", "", skRows(3)));
    if (!instSeq) loadInstalled();
    return;
  }
  const r = thingRow();
  if (inst.error || !r){
    paint(d.list, `<div class="field"><div class="notice ${inst.error ? "bad" : "warn"}">${esc(inst.error
      ? "could not read what is installed: " + inst.error
      : `${thingLabel()} is not installed on ${inst.name || "this node"} now: the Library installs it.`)}</div></div>`);
    return;
  }
  const may = inst.may || {};
  const ver = r.version && r.version !== "-" && r.version !== "present" ? r.version : "";
  // Its version and an update as the row wears them, then where it stands.
  const pills = `${ver ? `<span class="pill" title="installed">${esc(ver)}</span>` : ""}${r.update && r.latest ? ` <span class="pill warn">${esc(r.latest)} is out</span>` : ""}`;
  const head = pageHead({title: r.label, pills, facts: [
    ["Node", inst.name || ""],
  ], actions: `<span class="irow" data-irow="${esc(thingKey)}" data-style="display:contents">${instState(r)}${instActs(r, may)}</span>`});
  const err = !r.running && (r.kind === "toolchain" || r.kind === "pack") && inst?.job?.errors?.[r.name] ? `<div class="field"><div class="sub bad">${esc(inst.job.errors[r.name])}</div></div>` : "";
  const sects = (THING_SECTS[r.kind] || THING_SECTS.toolchain).map(([k, title, body]) => {
    const html = body(r);
    return html ? docSection("thing", k, title, "", `<div class="field irow idetail" data-irow="${esc(thingKey)}">${html}</div>`, {open: true}) : "";
  }).join("");
  paint(d.list, `<div data-instnode="${esc(instNode)}" data-thing="${esc(thingKey)}">${head}${err}${sects}</div>`);
  wireInstalled(d.el);
  if (thingAt){
    d.el.querySelector(`details.sect[data-sect="${CSS.escape("thing:" + thingAt)}"]`)?.scrollIntoView({block: "start"});
    thingAt = "";
  }
}
