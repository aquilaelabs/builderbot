// The notebook's Analysis view, the code base read out, and the preamble a
// session is handed. One classic script beside index.html, the shape tab-*.js
// has (docs/nodes.md §13): one file per notebook view (R60). A factory
// makeNotebook calls per notebook.

"use strict";

function nbAnalysisView({$, nb, project}){
  const anaFx = {level: "", find: ""};

  async function loadAnalysis(){
    const hint = $("anaHint"), list = $("anaList");
    if (!findings || findings.error) await loadFindings(!!findings?.error);
    nb.anaStamp = state?.reports_mtime ?? null;
    if (!findings || findings.loading){ hint.innerHTML = skel("word"); list.innerHTML = skel("rows"); return; }
    if (findings.error){ hint.textContent = "analysis: " + findings.error; return; }
    if (!findings.available){
      hint.textContent = "No scan results: the report folder is not mounted here.";
      list.innerHTML = "";
      return;
    }
    const rows = [];
    for (const rep of findings.reports)
      for (const f of rep.findings)
        if (f.project === project) rows.push(f);
    const lv = {};
    rows.forEach(f => lv[f.level] = (lv[f.level] || 0) + 1);
    const stat = Object.keys(lv).sort((a, b) => (LEVEL_ORDER[a] ?? 9) - (LEVEL_ORDER[b] ?? 9))
      .map(l => `${lv[l]} ${l}${lv[l] === 1 ? "" : "s"}`).join(", ");
    hint.textContent = rows.length
      ? `${stat}`
      : "No findings for this project in the latest scan.";
    // The same two filters the Analysis tab has, project-fixed: one slice of
    // narrowing shared by both surfaces, so learning one is learning the
    // other. The bar only appears when there is something to narrow.
    const shown = fxFilter(rows, anaFx);
    list.innerHTML = (rows.length ? fxBarBand(rows, anaFx) : "")
      + (rows.length && !shown.length
          ? `<div class="empty">nothing matches the filters</div>` : "")
      + findingsRulesHtml(shown);
    fxWireBar(list, anaFx, loadAnalysis);
    // By rule group, which is how the report is read: a rule split across a
    // page boundary would separate its own occurrences.
    // .rule, which is what findingsRulesHtml emits: .grp belongs to the other,
    // per-file renderer, so this matched nothing and paginate returned early:
    // a project with hundreds of findings drew every one of them at once while
    // every list beside it paged.
    paginate(list, ":scope > .rule", {key: "anaList", noun: "rules"});
  }

  // The half of the briefing a session cannot write. Staged behind the
  // panel's Save like the memories beside them, because this is an editor:
  // somebody rewords two rules and drops a third before they are done, and
  // writing each keystroke through would be three records of one decision.
  //
  // A rule is CONDITIONAL exactly when it has a trigger. There is no kind
  // field and no picker for one: the presence of a trigger is the answer,
  // which is one fact to keep true instead of two.
  // The code base, counted (git-tracked files by language): the tab's first
  // section, above the rules. Fetched beside them; a repository's count is
  // cached by commit on the server, so this is cheap after the first time.
  let codeData = null;
  // Asked on every show of the briefing, and by the rules load beside it:
  // one fetch answers everyone who asks while it is in flight (B218).
  let codeInFlight = null;
  function loadCodebase(){
    if (codeInFlight) return codeInFlight;
    codeInFlight = (async () => {
      try{
        const r = await bootFetch("/api/codebase?project=" + encodeURIComponent(project));
        codeData = await r.json();
      }catch(e){ codeData = {error: String(e)}; }
    })().finally(() => { codeInFlight = null; });
    return codeInFlight;
  }
  // GitHub's colors for the languages people recognize; a hue from the
  // name for the rest, so two rare ones do not come out the same.
  const LANG_COLOR = {Python: "#3572A5", JavaScript: "#f1e05a", TypeScript: "#3178c6", HTML: "#e34c26",
    CSS: "#663399", Shell: "#89e051", Kotlin: "#A97BFF", Java: "#b07219", Dart: "#00B4AB", Swift: "#F05138",
    Go: "#00ADD8", Rust: "#dea584", C: "#555555", "C++": "#f34b7d", "C#": "#178600", Ruby: "#701516",
    PHP: "#4F5D95", SQL: "#e38c00", Dockerfile: "#384d54", Makefile: "#427819", Lua: "#000080", Zig: "#ec915c",
    Gradle: "#02303a", SCSS: "#c6538c", Nix: "#7e7eff"};
  function langColor(name){
    if (LANG_COLOR[name]) return LANG_COLOR[name];
    let h = 0; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return `hsl(${h} 55% 55%)`;
  }
  const nfmt = n => Number(n || 0).toLocaleString();
  function codebaseSection(){
    const d = codeData;
    let status = "counting", body = `${skel("rows", 3)}`;
    if (d && d.error){ status = "no count"; body = `<div class="hint">${esc(d.error)}</div>`; }
    else if (d){
      const code = (d.languages || []).filter(l => l.kind === "code");
      const rest = (d.languages || []).filter(l => l.kind !== "code");
      status = `${nfmt(d.files)} file${d.files === 1 ? "" : "s"} · ${nfmt(d.lines)} line${d.lines === 1 ? "" : "s"}`;
      const bar = code.length
        ? `<div class="cbbar" role="img" aria-label="${esc(code.map(l => `${l.name} ${l.pct}%`).join(", "))}">${
            code.map(l => `<span style="width:${l.pct}%;background:${langColor(l.name)}" title="${esc(l.name)} ${l.pct}%"></span>`).join("")}</div>
           <div class="cblegend">${code.map(l => `<span><span class="dot" style="background:${langColor(l.name)}"></span>${esc(l.name)} <b>${l.pct}%</b><span class="n">${nfmt(l.lines)} lines in ${nfmt(l.files)}</span></span>`).join("")}</div>`
        : `<div class="hint">no code among the tracked files yet</div>`;
      const sk = d.skipped || {};
      const skipped = [sk.binary ? `${sk.binary} binar${sk.binary === 1 ? "y" : "ies"}` : "",
                       sk.vendored ? `${sk.vendored} vendored or minified` : "",
                       sk.large ? `${sk.large} over 4MB` : ""].filter(Boolean);
      body = `<div class="hint">${nfmt(d.code_lines)} lines of code in ${nfmt(d.code_files)} file${d.code_files === 1 ? "" : "s"}, tracked by git${
          d.commit ? ` at <code>${esc(d.commit.slice(0, 7))}</code>` : ""}. Nothing untracked or ignored is counted: build output, dist/, a stray archive.</div>
        ${bar}
        ${rest.length ? `<div class="hint cbfoot">Counted, not in the bar: ${rest.map(l => `${esc(l.name)} ${nfmt(l.lines)} line${l.lines === 1 ? "" : "s"}`).join(", ")}.${
          skipped.length ? ` Skipped: ${skipped.join(", ")}.` : ""}</div>`
        : skipped.length ? `<div class="hint cbfoot">Skipped: ${skipped.join(", ")}.</div>` : ""}`;
    }
    // Open on both sizes: the numbers are the answer, not a place to go and
    // look for one, and the rules under it are the fold that closes.
    return docSection("briefing", "codebase", briefTitle("codebase"), status, body, {open: true});
  }
  // ---- what a session is handed --------------------------------------------
  // The three stores this notebook already shows, joined into the one string
  // bb-tty puts in front of a session. Fetched rather than built here: the
  // order, the joins and the cap are preamble.py's, and a second assembly on
  // this side would be a tab that quietly stops describing what sessions get.
  nb.preData = null;
  async function loadPreamble(){
    try{
      const r = await bootFetch(`/api/preamble?project=${encodeURIComponent(project)}`);
      const j = await r.json();
      nb.preData = j.error ? {error: j.error} : j;
    }catch(e){ nb.preData = {error: String(e)}; }
    nb.drawRules();
  }
  const preSize = n => n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} bytes`;
  function preambleSection(){
    const d = nb.preData;
    let body, status = "", cls = "";
    if (!d){
      body = skel("rows", 3);
    } else if (d.error){
      body = `<div class="field"><div class="hint bad">${esc(d.error)}</div></div>`;
      status = "unavailable"; cls = "bad";
    } else if (!d.text){
      status = "none";
      body = `<div class="field"><div class="sub dim">No rules, no open roadmap `
           + `items and no open bugs, so a session here starts on CLAUDE.md alone.`
           + `</div></div>`;
    } else {
      // A part that has started saying less is seen here before a session
      // meets it: its size against its share, and what it left out.
      const short = (d.parts || []).filter(x => x.left);
      status = preSize(d.bytes) + (short.length ? `, ${short.map(x => x.name).join(" and ")} over ${
        short.length === 1 ? "its share" : "their shares"}` : "");
      cls = short.length ? "warn" : "";
      // Read-only, and a textarea rather than a <pre> because the thing
      // somebody wants to do with this is select all of it and take it
      // somewhere. uniform.mjs exempts a read-only textarea from the control
      // width: this is a page of text, not a field.
      body = `<div class="field">
        <div class="hint">Every session started here is handed this, on top of `
        + `the project's CLAUDE.md.</div>
        <textarea id="preText" readonly rows="16" spellcheck="false"
          aria-label="what a session started here is sent">${esc(d.text)}</textarea>
        <div class="sub dim" id="preParts">${
          (d.parts || []).map(x => `${esc(x.name)} ${preSize(x.bytes)}${
            x.share ? ` of ${preSize(x.share)}` : ""}`).join(" · ")
        }</div>${(d.topics || []).length ? `<div class="sub dim" id="preTopics">pointed at, not sent: ${
          d.topics.map(t => esc(t.slug)).join(", ")} (${preSize(d.topics.reduce((n, t) => n + t.bytes, 0))}), each read with bb help TOPIC</div>` : ""}${short.map(x => `<div class="sub warn">The ${esc(x.name)} part is over its share, so a `
          + `session's prompt leaves out ${esc(x.left)}. Nothing is lost: the notebook keeps all of it, `
          + `and a session reads the rest when it needs it.</div>`).join("")}
      </div>`;
    }
    return docSection("briefing", "preamble", briefTitle("preamble"),
                      status, body, {open: false, cls});
  }

  // ---- the brief it was started from -----------------------------------------
  // What the project was made with, from New project: waiting in the tree
  // for the first Claude session, or kept here once that session started,
  // sent or set aside (brief.py). Read on every show of this view, since it
  // changes once, when the first session starts, and nothing after that.
  nb.briefData = null;
  async function loadBrief(){
    try{
      const j = await (await bootFetch(`/api/brief?project=${encodeURIComponent(project)}`)).json();
      nb.briefData = j.error ? null : j;
    }catch(e){ nb.briefData = null; }
    nb.drawRules();
  }
  function briefSection(){
    const d = nb.briefData, k = d?.kept;
    if (!d || (!d.pending && !k)) return "";
    const by = k?.by ? ` by ${k.by}` : "";
    const line = d.pending
      ? "Waiting for the first Claude session: pressing Claude on this project opens it to change before it is sent."
      : k.sent ? `Sent as the first session's first prompt ${ago(k.at)}${by}. No session after that one reads it.`
      : `Set aside ${ago(k.at)}${by}, when the first session started without it.`;
    const body = `<div class="field"><div class="hint">${esc(line)}</div>
      <textarea id="briefKept" readonly rows="8" spellcheck="false"
        aria-label="the brief this project was started from">${esc(d.pending ? d.text : k.text)}</textarea></div>`;
    return docSection("briefing", "brief", briefTitle("brief"),
                      d.pending ? "waiting" : k.sent ? "sent" : "set aside", body, {open: false});
  }

  return {loadAnalysis, loadCodebase, codebaseSection, loadPreamble, preambleSection, loadBrief, briefSection};
}
