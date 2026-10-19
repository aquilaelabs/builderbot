// The Help page (R258, the operator 16 Oct): BuilderBot's own docs, read in
// the wiki's reader. The docs are listed beside the article in docs/README's
// groups (a picker above it on a phone), a long one opens with its contents
// box, a link to another doc opens it here, and the bar's search finds a
// line in any of them as it is typed, each result opening its doc at the
// section it sits in. Each doc has an address (#/help/install), so a link
// to one lands on it and Back walks the docs read.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

let helpIndex = null, helpErr = "", helpCur = "", helpRev = 0;
const helpDocs = {};                 // name -> {name, title, text} | {error}
const helpAsked = new Set();         // reads on their way
let helpQ = "", helpHits = null, helpMore = 0, helpTimer = 0, helpAnchor = "";

function openHelp(){
  openTab({kind: "help", arg: "__help", label: "Help"});
}

async function loadHelp(){
  if (!helpIndex){
    try{
      const j = await (await fetch("/api/help")).json();
      if (j.error) helpErr = j.error; else { helpIndex = j; helpErr = ""; }
    }catch(e){ helpErr = "the docs could not be read: " + e; }
    if (!helpCur && helpIndex) helpCur = helpIndex.home;
    helpRev++; drawPanes();
  }
  if (helpCur) helpRead(helpCur);
}

async function helpRead(name){
  if (helpDocs[name] || helpAsked.has(name)) return;
  helpAsked.add(name);
  try{
    helpDocs[name] = await (await fetch("/api/help?doc=" + encodeURIComponent(name))).json();
  }catch(e){ helpDocs[name] = {error: "could not be read: " + e}; }
  helpAsked.delete(name);
  helpRev++; drawPanes();
}

// Every doc the index lists, README first: what a link may open.
function helpNames(){
  return helpIndex ? [helpIndex.home, ...helpIndex.groups.flatMap(g => g.docs.map(d => d.name))] : [];
}

// To a doc, at a section of it when one is named; a navigation, so the
// address is pushed and Back comes back here.
function helpGo(name, anchor = ""){
  helpQ = ""; helpHits = null;
  const q = document.getElementById("helpQ");
  if (q) q.value = "";
  helpCur = name; helpAnchor = anchor;
  const to = "#/help" + (name && name !== helpIndex?.home ? "/" + encodeURIComponent(name) : "");
  if (location.hash !== to) history.pushState(null, "", to);
  helpRead(name);
  helpRev++; drawPanes();
  if (!anchor) document.querySelector(".doc.on")?.scrollTo?.({top: 0});
}

// A section by its anchor: the reader's own (wk-...), or a forge's as a
// doc's links write them, which drop what the reader's turn into dashes.
function helpScroll(anchor){
  const doc = document.querySelector(".doc.on .helptab .wkpage");
  if (!doc || !anchor) return false;
  const flat = s => s.toLowerCase().replace(/^wk-/, "").replace(/[^a-z0-9]/g, "");
  const h = doc.querySelector(`[id="${CSS.escape(anchor)}"]`) || doc.querySelector(`[id="wk-${CSS.escape(anchor)}"]`)
    || [...doc.querySelectorAll("h2[id], h3[id], h4[id], h5[id], h6[id]")].find(x => flat(x.id) === flat(anchor));
  if (!h) return false;
  h.scrollIntoView({block: "start", behavior: noMotion() ? "auto" : "smooth"});
  return true;
}

function helpNav(){
  const li = (name, title) => `<li><a href="#/help${name === helpIndex.home ? "" : "/" + esc(name)}" class="wklink${
    name === helpCur ? " on" : ""}" data-page="${esc(name)}"${name === helpCur ? ' aria-current="page"' : ""}>${esc(title)}</a></li>`;
  const list = `<ul>${li(helpIndex.home, helpIndex.title)}</ul>` + helpIndex.groups.map(g =>
    `<strong>${esc(g.group)}</strong><ul>${g.docs.map(d => li(d.name, d.title)).join("")}</ul>`).join("");
  const pick = `<label class="pick wkpick">Doc <select id="helpPick" aria-label="the doc to read">${
    optionList([{name: helpIndex.home, title: helpIndex.title}, ...helpIndex.groups.flatMap(g => g.docs)].map(d => [d.name, d.title]), helpCur)}</select></label>`;
  return `<nav class="wknav" aria-label="the docs">${list}</nav>${pick}`;
}

function helpArticle(){
  const doc = helpDocs[helpCur];
  const meta = helpIndex.groups.flatMap(g => g.docs).find(d => d.name === helpCur);
  if (!doc) return `<article class="wkarticle">${skel("lines", 12)}</article>`;
  if (doc.error) return `<article class="wkarticle"><div class="hint bad">${esc(doc.error)}</div></article>`;
  // The doc's own # title is the article's title, said once.
  let text = doc.text;
  const first = text.match(/^\s*#\s+(.*?)\s*\n/);
  if (first) text = text.slice(first[0].length);
  // A link out of the docs (../CONTRIBUTING.md, a script in the tree) has
  // nothing here to open: its words, not its Markdown.
  text = text.replace(/\[([^\]]*)\]\((?!https?:)([^)#]*\/[^)]*)\)/g, "$1");
  // A long doc's contents go two levels deep; every heading of one is a
  // list longer than the doc's first screen.
  let toc = wikiToc(text);
  if (toc.length > 30) toc = toc.filter(h => h.level <= 2);
  const box = toc.length >= 3 ? `<div class="wktoc"><div class="wktochead">Contents</div><ol>${
    toc.map(h => `<li class="l${h.level}"><a href="#" data-anchor="${esc(h.id)}">${esc(h.text)}</a></li>`).join("")}</ol></div>` : "";
  return `<article class="wkarticle" data-name="${esc(doc.name)}">
      <h2 class="wktitle">${esc(doc.title)}</h2>
      <div class="wkmeta">${meta?.blurb ? `${esc(meta.blurb)} · ` : ""}<span class="mono">docs/${esc(doc.name)}.md</span></div>
      ${box}<div class="wkpage">${wikiMarkdown(text)}</div></article>`;
}

// The search's results, in the article's place: each line found with its
// doc and the section it is under, the words marked.
function helpResults(){
  const words = helpQ.trim().split(/\s+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const mark = s => words.length ? esc(s).replace(new RegExp(`(${words.map(w => esc(w)).join("|")})`, "gi"), "<mark>$1</mark>") : esc(s);
  const n = helpHits.length;
  return `<article class="wkarticle helphits">
      <h2 class="wktitle">Search</h2>
      <div class="wkmeta">${n ? `${n}${helpMore ? "+" : ""} line${n === 1 ? "" : "s"} for “${esc(helpQ.trim())}”` : ""}</div>
      ${n ? helpHits.map(r => `<button type="button" class="row helphit" data-hit="${esc(r.doc)}" data-anchor="${esc(r.anchor)}">
          <span class="grow"><span class="name">${esc(r.title)}${r.heading ? ` <span class="dim">› ${esc(r.heading)}</span>` : ""}</span>
            <span class="sub">${mark(r.text)}</span></span></button>`).join("")
        : `<div class="empty">nothing in the docs says “${esc(helpQ.trim())}”</div>`}
    </article>`;
}

async function helpSearch(){
  const q = helpQ.trim();
  if (q.length < 2){ helpHits = null; helpRev++; drawPanes(); return; }
  try{
    const j = await (await fetch("/api/help?q=" + encodeURIComponent(q))).json();
    if (q !== helpQ.trim()) return;               // typed on meanwhile
    helpHits = j.results || []; helpMore = j.more || 0;
  }catch(e){ helpHits = []; }
  helpRev++; drawPanes();
}

function renderHelpInto(i){
  const d = docSurface(i, "help");
  if (!d) return;
  // The search, once: drawn the same every time, so what is typed in it
  // stays while the page under it redraws.
  if (!d.bar.querySelector("#helpQ")){
    d.setBar(`<input id="helpQ" type="search" placeholder="search the docs" aria-label="search the docs" autocomplete="off" spellcheck="false">`);
    const q = d.bar.querySelector("#helpQ");
    q.value = helpQ;
    q.oninput = () => { helpQ = q.value; clearTimeout(helpTimer); helpTimer = setTimeout(helpSearch, 220); };
    q.onkeydown = e => { if (e.key === "Escape" && q.value){ q.value = ""; helpQ = ""; helpHits = null; helpRev++; drawPanes(); } };
  }
  if (!helpIndex){
    d.list.innerHTML = helpErr ? `<div class="hint bad">${esc(helpErr)}</div>`
      : skTpl(`<div class="field wkreader"><nav class="wknav">${skRows(8)}</nav><article class="wkarticle">${skel("lines", 12)}</article></div>`);
    return;
  }
  if (!paint(d.list, `<div class="field wkreader">${helpNav()}${helpHits ? helpResults() : helpArticle()}</div>`)) return;
  const root = d.list;
  root.querySelectorAll(".wknav a[data-page]").forEach(a => a.onclick = e => { e.preventDefault(); helpGo(a.dataset.page); });
  const pick = root.querySelector("#helpPick");
  if (pick) pick.onchange = () => helpGo(pick.value);
  root.querySelectorAll(".wktoc a[data-anchor]").forEach(a => a.onclick = e => { e.preventDefault(); helpScroll(a.dataset.anchor); });
  root.querySelectorAll("[data-hit]").forEach(b => b.onclick = () => helpGo(b.dataset.hit, b.dataset.anchor));
  // A link in a doc: another doc opens here, at its section when it names
  // one; a section of this one scrolls to it; what is not a doc here says so.
  root.querySelectorAll(".wkpage a.wklink").forEach(a => a.onclick = e => {
    e.preventDefault();
    const [file, hash = ""] = (a.dataset.page || "").split("#");
    const name = file.replace(/\.md$/i, "");
    if (!name) return helpScroll(hash);
    if (helpNames().includes(name)) return helpGo(name, hash);
    notify(`${file} is not one of the docs here`);
  });
  if (helpAnchor && helpDocs[helpCur] && !helpDocs[helpCur].error){
    const a = helpAnchor;
    helpAnchor = "";
    requestAnimationFrame(() => helpScroll(a));
  }
}
