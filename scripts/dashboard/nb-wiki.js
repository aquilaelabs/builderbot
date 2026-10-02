// The notebook's Wiki view (R112): the project's wiki, its pages as rows
// you open to read, Edit on a row to rewrite it, New page at the top, and
// the head row's Export, Pull and Push. Writes through, like Bugs: a Save on
// a page is that page written, with no notebook foot behind it. The pages
// are kept by the controller as a forge-shaped repository (wiki.py), so
// Export is a zip of Markdown and Push sends them to the repository's own
// wiki when the project has push rights there. A session writes with
// bb wiki, under Claude may: Write the wiki. One classic script beside
// index.html (docs/design-language.md, Files): a factory makeNotebook calls
// per notebook.

"use strict";

// Markdown as a forge's wiki shows it, enough of it to read a page here:
// headings, paragraphs, lists, quotes, rules, fenced code, tables, emphasis,
// inline code, links and [[wiki links]]. Everything is escaped first and
// only these shapes are put back, so a page can carry no markup of its own
// into the dashboard; a link is followed only to http(s) or another page.
function wikiMarkdown(src){
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
      return /^[^:/]+$/.test(pageName) ? `<a href="#" class="wklink" data-page="${pageName}">${text || pageName}</a>` : m;
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
      const n = Math.min(6, m[1].length + 2);         // h1 in a page is a section, not the view's title
      out.push(`<h${n}>${inline(m[2])}</h${n}>`);
      i++;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)){
      out.push("<hr>");
      i++;
    } else if (/^\s*>/.test(l)){
      const body = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) body.push(lines[i].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${wikiMarkdown(body.join("\n"))}</blockquote>`);
    } else if (/^\s*([-*+]|\d+[.)])\s+/.test(l)){
      const ordered = /^\s*\d/.test(l), items = [];
      for (; i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i]); i++)
        items.push(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, "").replace(/^\[( |x)\]\s+/i, (_, x) => x.trim() ? "☑ " : "☐ "));
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map(x => `<li>${inline(x)}</li>`).join("")}</${tag}>`);
    } else if (/\|/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])){
      const head = cells(l), rows = [];
      for (i += 2; i < lines.length && /\|/.test(lines[i]) && lines[i].trim(); i++) rows.push(cells(lines[i]));
      out.push(`<table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${
        rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
    } else if (!l.trim()){
      i++;
    } else {
      const body = [];
      for (; i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|>|([-*+]|\d+[.)])\s)/.test(lines[i]); i++) body.push(lines[i]);
      out.push(`<p>${body.map(inline).join("<br>")}</p>`);
    }
  }
  return out.join("");
}

function nbWikiView({$, nb, project}){
  nb.wkData = null;
  nb.wkRev = null;
  nb.wkPages = {};          // name -> the page as last read
  nb.wkOpen = new Set();    // rows open to read
  nb.wkEdit = new Map();    // name -> what is typed into its editor
  nb.wkAdding = null;       // {name, text} while New page is unrolled
  nb.wkLog = false;
  const q = "?project=" + encodeURIComponent(project);

  // Whether something typed would be lost by a redraw from the server.
  const wikiDirty = () => nb.wkEdit.size > 0 || !!(nb.wkAdding && (nb.wkAdding.name || nb.wkAdding.text));
  nb.wikiDirty = wikiDirty;

  let inFlight = null;
  function loadWiki(){
    if (inFlight) return inFlight;
    inFlight = (async () => {
      try{ nb.wkData = await (await fetch("/api/wiki" + q)).json(); }
      catch(e){ nb.wkData = {error: String(e), pages: []}; }
      nb.wkRev = nb.wkData.rev ?? nb.wkRev;
      // A page that moved is read again when it is next open.
      const now = new Map((nb.wkData.pages || []).map(p => [p.name, p.rev]));
      for (const name of Object.keys(nb.wkPages))
        if (now.get(name) !== nb.wkPages[name].rev) delete nb.wkPages[name];
      for (const name of nb.wkOpen) if (!now.has(name)) nb.wkOpen.delete(name);
      drawWiki();
      await Promise.all([...nb.wkOpen].filter(n => !nb.wkPages[n]).map(readPage));
    })().finally(() => { inFlight = null; });
    return inFlight;
  }

  async function readPage(name){
    try{
      const r = await (await fetch("/api/wiki" + q + "&page=" + encodeURIComponent(name))).json();
      if (!r.error) nb.wkPages[name] = r;
      else nb.wkPages[name] = {error: r.error};
    }catch(e){ nb.wkPages[name] = {error: String(e)}; }
    drawWiki();
  }

  function head(){
    const d = nb.wkData || {};
    const n = (d.pages || []).length;
    const rem = d.remote;
    const where = rem?.label ? ` · ${rem.label}` : " · no remote, so Export is how it leaves";
    $("wkHint").textContent = d.error ? "the wiki could not be read" : `${n} page${n === 1 ? "" : "s"}${where}`;
    $("wkExport").disabled = !n;
    $("wkPull").hidden = !rem?.label;
    $("wkPush").hidden = !rem?.label;
    $("wkPush").disabled = !rem?.auth || !n;
    // Why Push is dead, on the row and not in a tooltip (the operator, 23
    // Sep): a phone has no hover.
    const why = rem?.label && !rem.auth
      ? `Push needs the project's push rights on ${rem.label}: grant them in the project's remote dialog. Pull works without them for a public wiki.` : "";
    $("wkWhy").textContent = why;
    $("wkWhy").hidden = !why;
  }

  function row(p){
    const open = nb.wkOpen.has(p.name) || nb.wkEdit.has(p.name);
    const editing = nb.wkEdit.has(p.name);
    const pg = nb.wkPages[p.name];
    const facts = [`${p.size} B`, p.by ? `by ${p.by}` : "", p.at ? ago(p.at) : ""].filter(Boolean).join(" · ");
    let body;
    if (editing){
      body = `${lbl("", "Markdown", "GitHub's wiki Markdown: [[Another page]] links to a page here")}
        <textarea class="wkText" spellcheck="true">${esc(nb.wkEdit.get(p.name))}</textarea>
        <div class="actbar macts"><span class="state">Save writes the page now</span>
          <button type="button" class="stop wkCancel">Cancel</button>
          <button type="button" class="primary wkSave">Save</button></div>`;
    } else if (!pg){
      body = `<div class="hint">loading…</div>`;
    } else if (pg.error){
      body = `<div class="hint bad">${esc(pg.error)}</div>`;
    } else {
      body = `<div class="wkpage">${wikiMarkdown(pg.text) || `<span class="dim">an empty page</span>`}</div>
        <div class="actbar macts"><span class="state">${esc(p.file)}</span>
          <button type="button" class="wkRename">Rename</button>
          <button type="button" class="danger wkRm">Remove</button>
          <button type="button" class="wkEdit">Edit</button></div>`;
    }
    return `<details class="bug wkrow${editing ? " editing" : ""}" data-name="${esc(p.name)}"${open ? " open" : ""}>
      <summary><span class="btitle">${esc(p.title)}</span><span class="dim wkfacts">${esc(facts)}</span></summary>
      <div class="body">${body}</div></details>`;
  }

  function drawWiki(){
    const box = $("wkBody");
    if (!box) return;
    head();
    const d = nb.wkData;
    if (!d){ box.innerHTML = ""; return; }
    if (d.error){ box.innerHTML = `<div class="field"><div class="hint bad">${esc(d.error)}</div></div>`; return; }
    const a = nb.wkAdding;
    const add = a
      ? `<div class="field wkadd">${lbl("wkNewName", "Page name", "Home is the page a forge opens first; _Sidebar and _Footer frame every page")}
          <input id="wkNewName" maxlength="100" autocomplete="off" placeholder="${(d.pages || []).length ? "Getting started" : "Home"}" value="${esc(a.name)}">
          ${lbl("", "Markdown")}
          <textarea class="wkText" id="wkNewText" spellcheck="true">${esc(a.text)}</textarea>
          <div class="actbar macts"><span class="state">Create writes the page now</span>
            <button type="button" class="stop" id="wkNewCancel">Cancel</button>
            <button type="button" class="primary" id="wkNewSave">Create</button></div></div>`
      : `<div class="addbar" data-add="wiki"><button type="button" id="wkNew">New page</button></div>`;
    const log = !nb.wkLog ? "" : `<div class="field wklog">${(d.history || []).length
        ? (d.history || []).map(h => `<div class="wklogrow"><span class="mono">${esc(h.commit)}</span> ${esc(h.what)} <span class="dim">· ${esc(h.by)} · ${esc(ago(h.at))}</span></div>`).join("")
        : `<span class="dim">nothing yet</span>`}</div>`;
    const pages = d.pages || [];
    box.innerHTML = log + add + (pages.length
      ? `<div class="field wklist">${pages.map(row).join("")}</div>`
      : `<div class="field"><div class="hint">No pages yet. Start with Home, the page a wiki opens on; a session adds pages with bb wiki save${
          d.gate === "deny" ? ", though this project's Claude may: Write the wiki is deny" : ""}.</div></div>`);
    wire(box);
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
    box.querySelectorAll(".wkrow").forEach(el => {
      const name = el.dataset.name;
      el.querySelector("summary").onclick = ev => {
        ev.preventDefault();
        if (nb.wkEdit.has(name)) return;            // an editor is put away with Cancel or Save
        if (nb.wkOpen.has(name)) nb.wkOpen.delete(name);
        else { nb.wkOpen.add(name); if (!nb.wkPages[name]) readPage(name); }
        drawWiki();
      };
      const ta = el.querySelector(".wkText");
      if (ta) ta.oninput = () => nb.wkEdit.set(name, ta.value);
      const on = (cls, fn) => { const b = el.querySelector(cls); if (b) b.onclick = fn; };
      on(".wkEdit", () => { nb.wkEdit.set(name, nb.wkPages[name]?.text || ""); drawWiki(); });
      on(".wkCancel", () => { nb.wkEdit.delete(name); drawWiki(); });
      on(".wkSave", async ev => {
        busy(ev.target, "Saving");
        const j = await post({action: "save", name, text: nb.wkEdit.get(name), base: nb.wkPages[name]?.rev || ""});
        unbusy(ev.target, "Save");
        if (!j) return;
        nb.wkEdit.delete(name);
        delete nb.wkPages[name];
        loadWiki();
      });
      on(".wkRm", async () => {
        if (!confirm(`Remove ${nb.wkPages[name]?.title || name} from the wiki? Its history keeps it, and a push takes it off the forge's wiki too.`)) return;
        if (await post({action: "remove", name, base: nb.wkPages[name]?.rev || ""})){
          nb.wkOpen.delete(name); loadWiki();
        }
      });
      on(".wkRename", async () => {
        const to = prompt("Rename the page to:", nb.wkPages[name]?.title || name);
        if (!to || !to.trim()) return;
        const j = await post({action: "rename", name, to});
        if (j){ nb.wkOpen.delete(name); nb.wkOpen.add(j.name); loadWiki(); }
      });
    });
    // A [[link]] opens that page's row and brings it into view.
    box.querySelectorAll(".wklink").forEach(a => a.onclick = ev => {
      ev.preventDefault();
      const target = (nb.wkData?.pages || []).find(p => p.name.toLowerCase() === a.dataset.page.replace(/ /g, "-").toLowerCase());
      if (!target){ notify(`no page called ${a.dataset.page} yet: New page makes it`); return; }
      nb.wkOpen.add(target.name);
      if (!nb.wkPages[target.name]) readPage(target.name); else drawWiki();
      requestAnimationFrame(() => $("wkBody").querySelector(`.wkrow[data-name="${CSS.escape(target.name)}"]`)
        ?.scrollIntoView({block: "nearest"}));
    });
    const nw = box.querySelector("#wkNew");
    if (nw) nw.onclick = () => { nb.wkAdding = {name: (nb.wkData?.pages || []).length ? "" : "Home", text: ""}; drawWiki(); box.querySelector("#wkNewName")?.focus(); };
    const nn = box.querySelector("#wkNewName"), nt = box.querySelector("#wkNewText");
    if (nn) nn.oninput = () => { nb.wkAdding.name = nn.value; };
    if (nt) nt.oninput = () => { nb.wkAdding.text = nt.value; };
    const nc = box.querySelector("#wkNewCancel");
    if (nc) nc.onclick = () => { nb.wkAdding = null; drawWiki(); };
    const ns = box.querySelector("#wkNewSave");
    if (ns) ns.onclick = async () => {
      const name = (nb.wkAdding?.name || "").trim();
      if (!name){ failed("a page needs a name"); return; }
      busy(ns, "Creating");
      const j = await post({action: "save", name, text: nb.wkAdding.text, base: ""});
      unbusy(ns, "Create");
      if (!j) return;
      nb.wkAdding = null;
      nb.wkOpen.add(j.name);
      loadWiki();
    };
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
    const j = await post({action: "push"});
    unbusy(ev.target, "Push");
    if (j) notify(`pushed the wiki to ${j.to}`);
  };

  // Another window's save, a session's bb wiki or a pull is news when it
  // moved past what this panel read and nothing typed here would be lost;
  // the notebook's watch asks this while the view is on screen.
  const wikiNews = k => !!nb.wkData && revs[k] !== nb.wkRev && !wikiDirty();

  return {loadWiki, wikiDirty, wikiNews};
}
