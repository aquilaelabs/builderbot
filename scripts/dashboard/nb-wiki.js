// The notebook's Wiki view (R112): the project's wiki, its pages as rows
// you open to read, Edit on a row to rewrite it, New page at the top, and
// the head row's Export, Pull and Push. Writes through, like Bugs: a Save on
// a page is that page written, with no notebook foot behind it. The pages
// are kept by the controller as a forge-shaped repository (wiki.py), so
// Export is a zip of Markdown and Push sends them to the repository's own
// wiki when the project has push rights there. A session writes with
// bb wiki, under Agents may: Write the wiki. One classic script beside
// index.html (docs/design-language.md, Files): a factory makeNotebook calls
// per notebook.

"use strict";

// Markdown as a forge's wiki shows it, enough of it to read a page here:
// headings, paragraphs, lists, quotes, rules, fenced code, tables, emphasis,
// inline code, links and [[wiki links]]. Everything is escaped first and
// only these shapes are put back, so a page can carry no markup of its own
// into the dashboard; a link is followed only to http(s) or another page.
function wikiMarkdown(src, titles){
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  const inline = s => {
    const code = [];
    let t = esc(s).replace(/`([^`]+)`/g, (_, c) => { code.push(c); return `\u0000${code.length - 1}\u0000`; });
    t = t.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, a, b) => {
      // GitHub's [[Text|Page]]: the text first, the page after the bar.
      const pageName = (b || a).trim(), text = a.trim();
      return `<a href="#" class="wklink" data-page="${pageName}">${text}</a>`;
    });
    t = t.replace(/!?\[([^\]]*)\]\(([^)\s]+)\)/g, (m, text, url) => {
      if (/^https?:\/\//i.test(url)) return `<a href="${url}" target="_blank" rel="noopener noreferrer">${text || url}</a>`;
      const pageName = url.replace(/\.md$/i, "").replace(/^\.\//, "");
      // A link whose words are its own file name ([how-it-works.md](...))
      // reads as the page's title where the caller knows it (B110): a file
      // name is the source's spelling, not what a reader looks for.
      const doc = pageName.replace(/#.*$/, ""), file = url.replace(/^\.\//, "").replace(/#.*$/, "");
      const words = titles?.[doc] && (!text || text === file || text === url) ? esc(titles[doc]) : text || pageName;
      return /^[^:/]+$/.test(pageName) ? `<a href="#" class="wklink" data-page="${pageName}">${words}</a>` : m;
    });
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>")
         .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>").replace(/(^|\W)_([^_\s][^_]*)_(?=\W|$)/g, "$1<em>$2</em>")
         .replace(/~~([^~]+)~~/g, "<del>$1</del>");
    return t.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${code[Number(i)]}</code>`);
  };
  const cells = l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  let i = 0;
  while (i < lines.length){
    const l = lines[i];
    let m;
    if (/^\s*```/.test(l)){
      const body = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) body.push(lines[i]);
      i++;
      out.push(`<pre><code>${esc(body.join("\n"))}</code></pre>`);
    } else if ((m = l.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/))){
      // A page's # is a section under the article's own title, the way an
      // encyclopedia article's headings sit under its name; each carries an
      // id the contents box links to.
      const n = Math.min(6, m[1].length + 1);
      out.push(`<h${n} id="${wikiSlug(m[2])}">${inline(m[2])}</h${n}>`);
      i++;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)){
      out.push("<hr>");
      i++;
    } else if (/^\s*>/.test(l)){
      const body = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) body.push(lines[i].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${wikiMarkdown(body.join("\n"), titles)}</blockquote>`);
    } else if (/^\s*([-*+]|\d+[.)])\s+/.test(l)){
      const ordered = /^\s*\d/.test(l), items = [];
      // An item's wrapped lines, indented under it, are the item's own.
      for (; i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i]); i++){
        items.push(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, "").replace(/^\[( |x)\]\s+/i, (_, x) => x.trim() ? "☑ " : "☐ "));
        while (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i + 1]))
          items[items.length - 1] += " " + lines[++i].trim();
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map(x => `<li>${inline(x)}</li>`).join("")}</${tag}>`);
    } else if (/\|/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])){
      const head = cells(l), rows = [];
      for (i += 2; i < lines.length && /\|/.test(lines[i]) && lines[i].trim(); i++) rows.push(cells(lines[i]));
      // A head with nothing in it (| | |, a table of label and value) is no
      // head: drawn, it was a blank first row (B78).
      out.push(`<table>${head.some(c => c.trim()) ? `<thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead>` : ""}<tbody>${
        rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
    } else if (!l.trim()){
      i++;
    } else {
      const body = [];
      for (; i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|>|([-*+]|\d+[.)])\s)/.test(lines[i]); i++) body.push(lines[i]);
      // A line break in the source is a space, as a forge shows a file; two
      // spaces at a line's end are a break of its own.
      out.push(`<p>${body.map((x, k) => inline(x.trim()) + (k === body.length - 1 ? "" : / {2,}$/.test(x) ? "<br>" : " ")).join("")}</p>`);
    }
  }
  return out.join("");
}

// A heading's anchor, the same from the renderer and the contents box.
function wikiSlug(t){
  return "wk-" + String(t).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// The page's headings, for its contents box: [{level, text, id}], outside
// fenced code, in order.
function wikiToc(src){
  const out = [];
  let fence = false;
  for (const l of String(src || "").split(/\r?\n/)){
    if (/^\s*```/.test(l)){ fence = !fence; continue; }
    const m = !fence && l.match(/^(#{1,3})\s+(.*?)\s*#*\s*$/);
    if (m) out.push({level: m[1].length, text: m[2].replace(/[*_`]/g, ""), id: wikiSlug(m[2])});
  }
  return out;
}

// ---- the reader, Help's and a project's Wiki view's ----------------------
// One reader for both (the operator, 19 Oct: so the two cannot drift): the
// list beside the article with its picker on a phone, the article's head,
// its contents box and its page. The Wiki view adds its Read and Edit tabs
// and its footer; Help adds its search.

// The list of pages beside the article, and the picker that stands for it
// on a phone, the word beside it as a page bar's picker has.
function wikiNav(list, aria, {id, word, items, cur}){
  return `<nav class="wknav" aria-label="${esc(aria)}">${list}</nav><label class="pick wkpick"><span class="pickw">${esc(word)}</span><select id="${esc(id)}" aria-label="${esc(aria)}">${
    optionList(items, cur)}</select></label>`;
}
// A page's text without its own # title when that title is said by the
// article's head: always for Help's docs, when it is the page's name in a
// wiki.
function wikiUntitled(text, title = null){
  const first = String(text || "").match(/^\s*#\s+(.*?)\s*\n/);
  return first && (title === null || first[1].trim().toLowerCase() === title.toLowerCase()) ? text.slice(first[0].length) : text;
}
// The contents box for a page with three headings or more; a long one's goes
// two levels deep, every heading of it being a list longer than the page's
// first screen. A press scrolls to its heading (wikiWireAnchors).
function wikiContents(text){
  let toc = wikiToc(text);
  if (toc.length > 30) toc = toc.filter(h => h.level <= 2);
  return toc.length >= 3 ? `<div class="wktoc"><div class="wktochead">Contents</div><ol>${
    toc.map(h => `<li class="l${h.level}"><a href="#" data-anchor="${esc(h.id)}">${esc(h.text)}</a></li>`).join("")}</ol></div>` : "";
}
// A heading of `root`'s page by its anchor, scrolled to the top of what
// scrolls: the reader's own id (wk-...), or a forge's as a doc's links write
// it, which drops what the reader's ids turn into dashes. The pane is what
// scrolls, so the pane is scrolled: scrollIntoView moved the PAGE instead,
// the heading went up under the header and the article sat where it was
// (the operator, 4 Oct). False when there is no such heading.
function wikiScroll(root, anchor){
  const doc = root?.querySelector(".wkpage");
  if (!doc || !anchor) return false;
  const flat = s => s.toLowerCase().replace(/^wk-/, "").replace(/[^a-z0-9]/g, "");
  const h = doc.querySelector(`[id="${CSS.escape(anchor)}"]`) || doc.querySelector(`[id="wk-${CSS.escape(anchor)}"]`)
    || [...doc.querySelectorAll("h2[id], h3[id], h4[id], h5[id], h6[id]")].find(x => flat(x.id) === flat(anchor));
  if (!h) return false;
  let sc = h.parentElement;
  while (sc && !(/(auto|scroll)/.test(getComputedStyle(sc).overflowY) && sc.scrollHeight > sc.clientHeight)) sc = sc.parentElement;
  if (!sc) return false;
  sc.scrollTo({top: sc.scrollTop + h.getBoundingClientRect().top - sc.getBoundingClientRect().top - 8,
               behavior: noMotion() ? "auto" : "smooth"});
  return true;
}
// The article: what goes over its title (the wiki's tabs), its title, the
// line under it, and its body.
function wikiArticle({name, title, meta, over = "", body}){
  return `<article class="wkarticle" data-name="${esc(name)}">${over}
      <h2 class="wktitle">${esc(title)}</h2>
      <div class="wkmeta">${meta}</div>
      ${body}</article>`;
}

function nbWikiView({$, nb, project}){
  // Read like an encyclopedia (the operator, 2 Oct): one article at a time,
  // its title over a rule, a contents box for a page with sections, and
  // the pages listed beside it (the wiki's own _Sidebar when it has one),
  // a picker above it on a phone. Read and Edit are tabs over the article.
  nb.wkData = null;
  nb.wkRev = null;
  nb.wkPages = {};          // name -> the page as last read
  nb.wkCur = "";            // the article on screen
  nb.wkEdit = null;         // {name, text} while its editor is open
  nb.wkAdding = null;       // {name, text} while New page is unrolled
  nb.wkLog = false;
  const q = "?project=" + encodeURIComponent(project);
  const SPECIAL = ["_Sidebar", "_Footer"];

  // Whether something typed would be lost by a redraw from the server.
  const wikiDirty = () => !!nb.wkEdit || !!(nb.wkAdding && (nb.wkAdding.name || nb.wkAdding.text));
  nb.wikiDirty = wikiDirty;
  nb.wikiClear = () => { nb.wkEdit = null; nb.wkAdding = null; };

  const pages = () => nb.wkData?.pages || [];
  const articles = () => pages().filter(p => !SPECIAL.includes(p.name));
  const byName = n => pages().find(p => p.name.toLowerCase() === String(n).replace(/ /g, "-").toLowerCase());

  let inFlight = null;
  function loadWiki(){
    if (inFlight) return inFlight;
    inFlight = (async () => {
      try{ nb.wkData = await (await fetch("/api/wiki" + q)).json(); }
      catch(e){ nb.wkData = {error: String(e), pages: []}; }
      nb.wkRev = nb.wkData.rev ?? nb.wkRev;
      // A page that moved is read again.
      const now = new Map(pages().map(p => [p.name, p.rev]));
      for (const name of Object.keys(nb.wkPages))
        if (now.get(name) !== nb.wkPages[name].rev) delete nb.wkPages[name];
      if (!nb.wkCur || !now.has(nb.wkCur))
        nb.wkCur = (byName("Home") || articles()[0])?.name || "";
      drawWiki();
      const want = [nb.wkCur, ...SPECIAL.filter(n => now.has(n))].filter(n => n && !nb.wkPages[n]);
      await Promise.all(want.map(readPage));
    })().finally(() => { inFlight = null; });
    return inFlight;
  }

  async function readPage(name){
    try{
      const r = await (await fetch("/api/wiki" + q + "&page=" + encodeURIComponent(name))).json();
      nb.wkPages[name] = r.error ? {error: r.error} : r;
    }catch(e){ nb.wkPages[name] = {error: String(e)}; }
    drawWiki();
  }

  function go(name){
    const p = byName(name);
    if (!p){ notify(`no page called ${name} yet: New page makes it`); return; }
    if (wikiDirty() && !confirm("Leave the page you are editing? What you typed is not saved.")) return;
    nb.wikiClear();
    // A history entry (R256 step 3): the address names the page, and Back
    // returns to the one before.
    navPush(() => { nb.wkCur = p.name; shellSync(); });
    if (!nb.wkPages[p.name]) readPage(p.name); else drawWiki();
    $("wkBody")?.querySelector(".wkarticle")?.scrollIntoView({block: "nearest"});
  }
  // The page an address names: before the wiki is read, it is the page the
  // read lands on; after, it is opened as a press would.
  nb.wikiAt = name => {
    if (!nb.wkData){ nb.wkCur = name; return; }
    const p = byName(name);
    if (p && p.name !== nb.wkCur){ nb.wkCur = p.name; if (!nb.wkPages[p.name]) readPage(p.name); else drawWiki(); }
  };

  function head(){
    const d = nb.wkData || {};
    const n = articles().length;
    const rem = d.remote;
    $("wkHint").textContent = d.error ? "wiki: " + d.error : `${n} page${n === 1 ? "" : "s"}`;
    $("wkExport").disabled = !pages().length;
    $("wkPull").hidden = $("wkPush").hidden = !rem?.label;
    // An empty wiki is its empty state, not a fault: the bar's own line
    // says its buttons wait for a page, in the bar's voice, not in red.
    $("wkNetState").textContent = (rem?.label ? `${rem.label}'s wiki` : "no remote: Export is how it leaves")
      + (pages().length ? "" : rem?.label ? "; Export and Push wait for a page" : "; it waits for a page");
    // A role that reads the project and does not write it (B101): Pull and
    // Push dead, and that is the reason said under them.
    const ro = projWriteWhy(project);
    $("wkPull").disabled = !!ro;
    $("wkPush").disabled = !!ro || !rem?.auth || !pages().length;
    // Why Push is dead, on the row and not in a tooltip (the operator, 23
    // Sep): a phone has no hover.
    const why = ro && rem?.label ? ro : pages().length && rem?.label && !rem.auth
      ? `Push needs the project's push rights on ${rem.label}: grant them in the project's remote dialog. Pull works without them for a public wiki.` : "";
    $("wkWhy").textContent = why;
    $("wkWhy").hidden = !why;
  }

  // The list beside the article: the wiki's own _Sidebar when it has one,
  // drawn from its Markdown like any page, else every article by name.
  function nav(){
    const sb = nb.wkPages._Sidebar;
    const list = sb && !sb.error
      ? wikiMarkdown(sb.text)
      : `<ul>${articles().map(p => `<li><a href="#" class="wklink" data-page="${esc(p.name)}">${esc(p.title)}</a></li>`).join("")}</ul>`;
    return wikiNav(list, "the wiki's pages", {id: "wkPick", word: "Page", items: articles().map(p => [p.name, p.title]), cur: nb.wkCur});
  }

  function article(){
    const meta = byName(nb.wkCur);
    if (!meta) return `<article class="wkarticle"><div class="hint">No pages yet. Start with Home, the page a wiki opens on; a session adds pages with bb wiki save${
      nb.wkData?.gate === "deny" ? ", though this project's Agents may: Write the wiki is deny" : ""}.</div></article>`;
    const pg = nb.wkPages[meta.name];
    // A reader (B101) gets no Edit, Rename or Remove on a page: New page,
    // dead above, says why.
    const ro = projWriteWhy(project);
    const editing = !ro && nb.wkEdit && nb.wkEdit.name === meta.name;
    const tabs = `<div class="wktabs" role="tablist">
        <button type="button" class="wktab${editing ? "" : " on"}" id="wkRead" role="tab" aria-selected="${!editing}">Read</button>${ro ? "" : `
        <button type="button" class="wktab${editing ? " on" : ""}" id="wkEditTab" role="tab" aria-selected="${!!editing}"${pg && !pg.error ? "" : " disabled"}>Edit</button>
        <span class="sp"></span>
        <button type="button" class="wktab" id="wkRename">Rename</button>
        <button type="button" class="wktab danger" id="wkRm">Remove</button>`}</div>`;
    let body;
    if (editing){
      body = `${lbl("wkText", "Markdown", "GitHub's wiki Markdown: [[Another page]] links to a page here")}
        <textarea class="wkText" id="wkText" spellcheck="true">${esc(nb.wkEdit.text)}</textarea>
        <div class="actbar macts"><span class="state">Save writes the page now</span>
          <button type="button" class="stop" id="wkCancel">Cancel</button>
          <button type="button" class="primary" id="wkSave">Save</button></div>`;
    } else if (!pg){
      body = `${skel("lines", 9)}`;
    } else if (pg.error){
      body = `<div class="hint bad">${esc(pg.error)}</div>`;
    } else {
      // A page that opens with its own title as a # heading says it once.
      const text = wikiUntitled(pg.text, meta.title);
      const foot = nb.wkPages._Footer && !nb.wkPages._Footer.error
        ? `<footer class="wkfooter">${wikiMarkdown(nb.wkPages._Footer.text)}</footer>` : "";
      body = `${wikiContents(text)}<div class="wkpage">${wikiMarkdown(text) || `<span class="dim">an empty page</span>`}</div>${foot}`;
    }
    return wikiArticle({name: meta.name, title: meta.title, over: tabs, body,
      meta: [meta.by ? `last edited by ${esc(meta.by)}` : "", meta.at ? esc(ago(meta.at)) : "",
             `<span class="mono">${esc(meta.file)}</span>`].filter(Boolean).join(" · ")});
  }

  function drawWiki(){
    const box = $("wkBody");
    if (!box) return;
    head();
    const d = nb.wkData;
    if (!d){ box.innerHTML = ""; return; }
    if (d.error){ box.innerHTML = `<div class="field"><div class="hint bad">${esc(d.error)}</div></div>`; return; }
    const ro = projWriteWhy(project);
    const a = ro ? null : nb.wkAdding;
    const add = a
      ? `<div class="field wkadd">${lbl("wkNewName", "Page name", "Home is the page a wiki opens on; _Sidebar and _Footer frame every page")}
          <input id="wkNewName" maxlength="200" autocomplete="off" placeholder="${articles().length ? "Getting started" : "Home"}" value="${esc(a.name)}">
          ${lbl("wkNewText", "Markdown")}
          <textarea class="wkText" id="wkNewText" spellcheck="true">${esc(a.text)}</textarea>
          <div class="actbar macts"><span class="state">Create writes the page now</span>
            <button type="button" class="stop" id="wkNewCancel">Cancel</button>
            <button type="button" class="primary" id="wkNewSave">Create</button></div></div>`
      : ro ? ""
      : `<div class="field"><div class="addbar ctlrow" data-add="wiki"><button type="button" id="wkNew">New page</button></div></div>`;
    const log = !nb.wkLog ? "" : `<div class="field wklog">${(d.history || []).length
        ? (d.history || []).map(h => `<div class="wklogrow"><span class="mono">${esc(h.commit)}</span> ${esc(h.what)} <span class="dim">· ${esc(h.by)} · ${esc(ago(h.at))}</span></div>`).join("")
        : `<span class="dim">nothing yet</span>`}</div>`;
    // The add band is the first band under the head, above where the wiki
    // goes (B457); the rest is the body.
    $("wkAddBox").innerHTML = add;
    box.innerHTML = log + `<div class="field wkreader">${articles().length ? nav() : ""}${article()}</div>`;
    wire(box);
    wire($("wkAddBox"));
  }

  function failed(msg){ notify(msg, true); }

  async function post(body){
    const r = await postJSON("/api/wiki", {project, ...body});
    let j = {};
    try{ j = await r.json(); }catch{ j = {error: `the controller answered ${r.status}`}; }
    if (!r.ok || j.error){ failed(j.error || `the controller answered ${r.status}`); return null; }
    return j;
  }

  function wire(box){
    const on = (id, fn) => { const b = box.querySelector("#" + id); if (b) b.onclick = fn; };
    const name = nb.wkCur;
    // A [[link]], the nav's and the sidebar's: that page, in place.
    // A link to a page the wiki does not have is drawn as one, the way an
    // encyclopedia draws a red link: pressed, it says New page makes it.
    box.querySelectorAll(".wklink").forEach(a => {
      a.classList.toggle("wkmissing", !!nb.wkData && !byName(a.dataset.page));
      a.onclick = ev => { ev.preventDefault(); go(a.dataset.page); };
    });
    box.querySelectorAll("[data-anchor]").forEach(a => a.onclick = ev => { ev.preventDefault(); wikiScroll(box, a.dataset.anchor); });
    const pick = box.querySelector("#wkPick");
    if (pick) pick.onchange = () => go(pick.value);
    on("wkRead", () => { if (nb.wkEdit && !confirm("Stop editing? What you typed is not saved.")) return; nb.wkEdit = null; drawWiki(); });
    on("wkEditTab", () => { nb.wkEdit = {name, text: nb.wkPages[name]?.text || ""}; drawWiki(); box.querySelector("#wkText")?.focus(); });
    const ta = box.querySelector("#wkText");
    if (ta) ta.oninput = () => { nb.wkEdit.text = ta.value; };
    on("wkCancel", () => { nb.wkEdit = null; drawWiki(); });
    on("wkSave", async ev => {
      busy(ev.target, "Saving");
      const j = await post({action: "save", name, text: nb.wkEdit.text, base: nb.wkPages[name]?.rev || ""});
      if (ev.target.isConnected) unbusy(ev.target, "Save");
      if (!j) return;
      nb.wkEdit = null;
      delete nb.wkPages[name];
      loadWiki();
    });
    on("wkRm", async () => {
      if (!confirm(`Remove ${byName(name)?.title || name} from the wiki? Its history keeps it, and a push takes it off the forge's wiki too.`)) return;
      if (await post({action: "remove", name, base: nb.wkPages[name]?.rev || ""})){
        nb.wkCur = ""; loadWiki();
      }
    });
    on("wkRename", async () => {
      const at = $("wkBody")?.querySelector(".wktabs");
      const to = at ? await askInline(at, {label: "The page's new name", value: byName(name)?.title || name, ok: "Rename"})
        : prompt("Rename the page to:", byName(name)?.title || name);
      if (!to || !to.trim()) return;
      const j = await post({action: "rename", name, to});
      if (!j) return;
      if (j.relinked) notify(`Renamed; the links to it on ${j.relinked} page${j.relinked === 1 ? "" : "s"} now use its new name`);
      nb.wkCur = j.name; loadWiki();
    });
    on("wkNew", () => {
      nb.wkAdding = {name: articles().length ? "" : "Home", text: ""};
      drawWiki(); box.querySelector("#wkNewName")?.focus();
    });
    const nn = box.querySelector("#wkNewName"), nt = box.querySelector("#wkNewText");
    if (nn) nn.oninput = () => { nb.wkAdding.name = nn.value; };
    if (nt) nt.oninput = () => { nb.wkAdding.text = nt.value; };
    on("wkNewCancel", () => { nb.wkAdding = null; drawWiki(); });
    on("wkNewSave", async ev => {
      const n = (nb.wkAdding?.name || "").trim();
      if (!n){ failed("a page needs a name"); return; }
      busy(ev.target, "Creating");
      const j = await post({action: "save", name: n, text: nb.wkAdding.text, base: ""});
      if (ev.target.isConnected) unbusy(ev.target, "Create");
      if (!j) return;
      nb.wkAdding = null;
      nb.wkCur = j.name;
      loadWiki();
    });
  }

  // The head row's controls: wired once, they live in the markup.
  $("wkExport").onclick = () => { location.href = "/api/wiki-export" + q; };
  $("wkLogBtn").onclick = () => { nb.wkLog = !nb.wkLog; drawWiki(); };
  $("wkPull").onclick = async ev => {
    busy(ev.target, "Pulling");
    const j = await post({action: "pull"});
    unbusy(ev.target, "Pull");
    if (j){ notify(j.took === "all" ? `took in ${j.pages} page${j.pages === 1 ? "" : "s"} from the forge's wiki`
                                    : "took in the forge's wiki's changes"); nb.wkPages = {}; loadWiki(); }
  };
  $("wkPush").onclick = async ev => {
    if (wikiDirty() && !confirm("A page is being edited and is not saved: push what is saved?")) return;
    busy(ev.target, "Pushing");
    const r = await postJSON("/api/wiki", {project, action: "push"});
    let j = await r.json().catch(() => ({}));
    // The forge has something this wiki has not: most often the one page
    // GitHub makes you save before a wiki exists. Replacing it is offered,
    // said for what it is.
    if (j.error && /has not taken in/.test(j.error)
        && confirm(`${j.error}.\n\nReplace the forge's wiki with this one? Pages there that are not here are removed from it (its own history keeps them). Cancel, then Pull, to merge instead.`)){
      const r2 = await postJSON("/api/wiki", {project, action: "push", replace: true});
      j = await r2.json().catch(() => ({}));
    }
    unbusy(ev.target, "Push");
    if (j.error) failed(j.error); else if (j.to) notify(`pushed the wiki to ${j.to}`);
  };

  // Another window's save, a session's bb wiki or a pull is news when it
  // moved past what this panel read and nothing typed here would be lost;
  // the notebook's watch asks this while the view is on screen.
  const wikiNews = k => !!nb.wkData && revs[k] !== nb.wkRev && !wikiDirty();

  return {loadWiki, wikiDirty, wikiNews};
}
