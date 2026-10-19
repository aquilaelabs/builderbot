// The notebook's Git view: the repository read out, its branches, its
// commits, the policy that says what a session may push, and Send to Claude.
// One classic script beside index.html, the shape tab-*.js has (docs/nodes.md
// §13): same page, same global scope, one file per notebook view (R60).
//
// A factory rather than a script that runs: makeNotebook calls it per
// notebook with the notebook's element lookup, its state object and its
// project, and takes back the one function the rest of the notebook calls.

"use strict";
// The view's steady sections in their order, by the titles they are drawn
// under: the view and its placeholder (page-docs.js SKTPLS.git) both read
// them, so neither falls behind the other (R218, the operator 18 Oct). CI
// and a README come only with what the repository holds.
const GIT_SECTS = [["changes", "Changes"], ["history", "History"], ["branches", "Branches"], ["policy", "Claude may"]];
const gitTitle = k => (GIT_SECTS.find(s => s[0] === k) || [k, k])[1];
// The branches table's columns (R269 step 1), read by the view and by its
// placeholder (page-docs.js SKTPLS.git), so the wait draws the same table.
const gitBranchCols = main => [{label: "Branch"}, {label: "Updated", w: "minmax(0,.55fr)"}, {label: `Behind | ahead of ${main}`, w: "9rem"},
                               {label: "Owner", w: "minmax(0,.45fr)"}, {act: true, w: "3rem"}];

function nbGitView({$, nb, project}){
  // ---- git -----------------------------------------------------------------
  // The repository, read out (roadmap R36 step 1). Fetched on open and on
  // the git revision (the tree's HEAD log moving) never on the poll: a
  // history is a git call per question. What is open stays open across a
  // redraw: the commit picked and the files unfolded are kept by sha and
  // path, not by position.
  let git = null, gitPick = "", gitOpenFiles = new Set();
  // The branch whose comparison with main is on show, its own page (R269
  // step 2: #/projects/NAME/git/compare/BRANCH), "" for the view itself;
  // and what that page last read, by the two heads it was read at.
  let gitCmp = "", gitCmpData = null, gitHintText = "";
  // Which branches the table shows (R269 step 1): a chip, Active until one
  // is pressed, and the search typed beside it; a view, never saved.
  let gitBranchChip = "active", gitBranchFind = "";
  // What an open fold last showed, by what it shows (B833): a redraw draws
  // the view whole, and every open diff and comparison used to read itself
  // again on each one, a hundred reads in a few minutes on the controller.
  // A file's is kept against its state and stamp, a branch's against its
  // head and main's, and read again only when one moved.
  const gitKept = {file: {}};
  const keptBody = (kind, id, key, wait) => gitKept[kind][id]?.key === key ? gitKept[kind][id].html : wait;
  // ...and one read at a time per fold and key: a commit moves the view
  // twice (its add, then itself), and the second redraw came before the
  // first answer. The answer fills the fold on screen when it lands,
  // whichever draw that one is.
  const gitAsking = new Set();
  async function keptLoad(kind, d, sel, id, url, render){
    const key = d.dataset.key, ask = `${kind}\n${id}\n${key}`;
    if (gitAsking.has(ask)) return;
    gitAsking.add(ask);
    let html, ok = false;
    try{
      const j = await (await fetch(url)).json();
      html = j.error ? `<div class="hint bad">${esc(j.error)}</div>` : render(j);
      ok = !j.error;
    }catch(e){ html = `<div class="hint bad">${esc(String(e))}</div>`; }
    finally{ gitAsking.delete(ask); }
    if (ok) gitKept[kind][id] = {key, html};
    const at = `.gfile[data-path="${CSS.escape(id)}"]`;
    const now = $("gitBody")?.querySelector(at);
    for (const fold of new Set([d, now])) if (fold?.dataset.key === key) fold.querySelector(sel).innerHTML = html;
  }
  // The commit a click picked, until its detail has drawn and been scrolled
  // to: the detail sits under the whole history, so a long one leaves the
  // change below the fold. A redraw from a poll leaves the page where it is.
  let gitReveal = "";
  let gitMsgDraft = "";                            // typed and not sent, across redraws
  let gitPolDraft = {};                            // the policy picked and not applied
  const GITPOL_DEFAULT = {push: "allow", main: "deny", scan: "hold"};   // prefs.GITPOL_DEFAULT

  // Send to Claude: the thing picked and what is asked of it, composed on
  // the controller and typed into the project's session the way a roadmap
  // step arrives; then the tab, so the answer is watched.
  async function gitAsk(kind, args, btn){
    // Asked first (sendSure), except where the caller already asked about
    // this very send: another session's branch to merge or rebase.
    const what = args?.path ? `${args.path} (${kind})`
      : args?.branch ? `the branch ${args.branch} (${kind})`
      : args?.sha ? `the commit ${String(args.sha).slice(0, 7)} (${kind})`
      : `the ${kind}`;
    if (!args?.confirmed && !sendSure(project, what)) return;
    if (btn) busy(btn, "Sending");
    try{
      const r = await postJSON("/api/git", {project, action: "ask", kind, args: args || {}});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      if (!j.sent) notify("Not sent: the session is busy. Press Enter in its tab when it is free.", true);
      startClaude(project, null);
    }catch(e){ notify("ask: " + e, true); }
    finally{ if (btn && btn.isConnected) unbusy(btn, btn.dataset.label || btn.textContent); }
  }
  // The project directory is the owner's working tree (B236): anybody else
  // sees whose it is, a plain account gets nothing that changes it, and an
  // administrator is asked by the server first.
  const treeOf = () => {
    const owner = git?.owner || "", notMine = !!owner && owner !== state?.me;
    return {owner, notMine, barred: notMine && !state?.admin};
  };
  async function loadGit(){
    const hint = $("gitHint"), body = $("gitBody");
    try{
      const r = await fetch("/api/git?project=" + encodeURIComponent(project) + "&what=all");
      git = await r.json();
    }catch(e){ hint.textContent = "git: " + e; return; }
    if (git.error){
      const none = git.error === "not a git repository";
      hint.textContent = none ? "no repository yet" : "git: " + git.error;
      // The way on, where the dead end was: Init makes the repository here
      // (a project adopted from a directory, or unpacked from an archive
      // without one), and a session then commits and pushes as anywhere.
      body.innerHTML = none ? `<div class="field actbar">
          <span class="state">Init makes one, on main, with nothing committed; a session can then version, build and push.</span>
          <button type="button" data-gitinit="1">Init repository</button></div>` : "";
      const b = body.querySelector("[data-gitinit]");
      if (b) b.onclick = () => gitAct("init", {}, b, "Making");
      return;
    }
    const st = git.status || {}, files = st.files || [], commits = git.commits || [];
    const local = (git.branches || []).filter(b => !b.remote);
    const tree = treeOf();
    // The branch is the picker's to say beside it (R269 step 3); the words
    // name one only when there is none to pick.
    gitHintText = hint.textContent = `${tree.notMine ? `${tree.owner}'s working tree, ` : ""}${st.branch ? "" : "on no branch · "}${files.length
      ? `${files.length} change${files.length === 1 ? "" : "s"} not committed` : "nothing uncommitted"} · ${
      // A branch with no commit is not listed by git, so "0 branches" sat
      // beside "on master" (B456): the honest word is that nothing is
      // committed yet.
      !commits.length ? "no commits yet" : `${local.length} branch${local.length === 1 ? "" : "es"}`}${
      st.upstream ? (st.ahead || st.behind
        ? ` · ${st.ahead ? st.ahead + " to push" : ""}${st.ahead && st.behind ? ", " : ""}${st.behind ? st.behind + " to pull" : ""} (${git.host?.name || "the remote"})`
        : ` · in step with ${git.host?.name || "the remote"}`) : ""}`;
    const net = $("gitNet");
    if (net){
      const locked = !!(state?.projects || []).find(p => p.name === project)?.locked;
      net.hidden = locked || !git.remote;
      $("gitNetState").textContent = !git.remote ? "" : !git.push
        ? "no push rights: fetch and pull only; rights are granted in the clone dialog"
        : st.upstream ? (st.ahead && st.behind
          ? `pull first: ${git.host?.name || "the remote"} has ${st.behind} commit${st.behind === 1 ? "" : "s"} this branch does not, and this branch has ${st.ahead} to push (${st.upstream})`
          : `${git.host?.name || "the remote"}, ${st.upstream}${st.ahead ? ` · ${st.ahead} to push` : ""}${st.behind ? ` · ${st.behind} to pull` : ""}`)
        : "no upstream yet: Push sets one";
      net.querySelector('[data-gitact="push"]').disabled = !git.push;
      net.querySelector('[data-gitact="pull"]').disabled = !st.upstream;
      net.querySelector('[data-gitact="pull"]').hidden = tree.barred;
    }
    drawGit();
  }

  // One action on the repository: a fixed command on the controller with
  // checked arguments (git.py). The view reloads on the answer, and on the
  // git revision when the tree's history moves.
  async function gitAct(action, args, btn, verb){
    if (btn) busy(btn, verb || "Working");
    try{
      const r = await postJSON("/api/git", {project, action, args: args || {}});
      const j = await r.json();
      if (j.error){
        if (j.unmerged && confirm(`${j.error}.\n\nDelete it anyway?`))
          return gitAct(action, {...args, force: true}, btn, verb);
        // Two branches with no commit in common (B234): usually the wrong
        // branch, and exactly right for a project that began without a
        // repository, so it is asked.
        if (j.unrelated && confirm(`${j.error}.\n\nMerging joins them into one history. Join them?`))
          return gitAct(action, {...args, unrelated: true}, btn, verb);
        // A page drawn before the branch became somebody's: the server asks.
        if (j.confirm){
          if (confirm(j.confirm)) return gitAct(action, {...args, confirmed: true}, btn, verb);
          return j;
        }
        notify(j.error, true);
        return j;
      }
      notify(j.out ? j.out.split("\n").slice(-1)[0] : `${action} done`);
      await loadGit();
      return j;
    }catch(e){ notify("git: " + e, true); return {error: String(e)}; }
    finally{ if (btn && btn.isConnected) unbusy(btn, btn.dataset.label || btn.textContent); }
  }
  const gitBusy = (btn, verb) => { btn.dataset.label = btn.dataset.label || btn.textContent; return btn; };
  $("gitNet")?.querySelectorAll("[data-gitact]").forEach(b => b.onclick = () =>
    gitAct(b.dataset.gitact, {}, gitBusy(b), {fetch: "Fetching", pull: "Pulling", push: "Pushing"}[b.dataset.gitact]));

  // The project's CI as the watch last found it (R117): looked at once a
  // day and when the project is linked, from the workflows in the tree and,
  // for a project on GitHub, its newest run on the main branch and the
  // notices GitHub wrote on it. Shown only where there are workflows.
  function ciSection(){
    const ci = git.ci || {};
    if (!ci.at && !ci.workflows && !git.remote) return "";
    const fs = ci.findings || [];
    const red = fs.some(f => f.sev === "bad");
    const status = !ci.at ? "not looked at yet" : red ? "failing" : fs.length ? `${fs.length} to look at` : "nothing drifting";
    const cls = red ? "bad" : fs.length ? "note" : ci.at ? "ok" : "";
    const word = {run: "Check", label: "Runner", action: "Action", notice: "GitHub says"};
    // A moving label and an action a major behind carry their fix (R117
    // step 4): Fix writes that one line into the working tree, uncommitted,
    // for Changes to show; nothing is committed or pushed by the press.
    const locked = !!(state?.projects || []).find(p => p.name === project)?.locked;
    const mayFix = !locked && !treeOf().barred;
    const rows = fs.map(f => `<div class="actbar"><span class="state ${f.sev === "bad" ? "bad" : f.sev === "warn" ? "warn" : ""}">${
        esc(word[f.kind] || f.kind)}: ${esc(f.text)} <code>${esc(f.where || "")}</code></span>${
        f.fix && mayFix ? `<button type="button" data-cifix="${esc(f.where)}"
          title="write ${esc(f.fix.to)} on that line, in the working tree; you commit it">Fix</button>` : ""}</div>`).join("");
    const run = ci.run?.id ? ` The newest run on ${esc(ci.run.branch)} ${esc(ci.run.ended || "ended " + ci.run.conclusion)}.` : "";
    const body = `<div class="sub dim">${ci.at ? `Looked ${esc(ago(ci.at))}${ci.repo ? ` at ${esc(ci.repo)} on GitHub` : ""}.${run}` :
        "Not looked at yet."} Looked at once a day and when the project is linked; a session reads a run with bb ci-log.</div>${
      ci.error ? `<div class="sub bad">${esc(ci.error)}</div>` : ""}${rows}
      <div class="actbar"><button type="button" id="gitCiLook">Look now</button></div>`;
    return docSection("git", "ci", "CI", status, body, {cls, open: red, loud: red});
  }

  // The chip in force and the search, laid over the table without a redraw:
  // a row shows when its kind is the chip's (Yours: the reader's sessions')
  // and its name holds what is typed; the line of branches already in main
  // shows under every chip but its own.
  function gitBranchShow(root){
    const q = gitBranchFind.trim().toLowerCase();
    let n = 0;
    root.querySelectorAll(".gbranch").forEach(r => {
      const c = gitBranchChip, k = r.dataset.kind;
      const on = (!c || (c === "mine" ? r.hasAttribute("data-mine") : k === c)) && (!q || r.dataset.branch.toLowerCase().includes(q));
      r.hidden = !on; n += on;
    });
    const none = root.querySelector(".gbnone");
    if (none) none.hidden = n > 0;
  }
  function drawGit(){
    const body = $("gitBody");
    if (!git || git.error) return;
    // A comparison's page stands in place of the view's sections and its
    // network bar, under the same head.
    body.closest(".nbview")?.classList.toggle("gcmpmode", !!gitCmp);
    // ...and the half not on show is emptied, so a phone's one section open
    // at a time is chosen among the sections drawn, not the hidden ones.
    if (gitCmp){ body.innerHTML = ""; drawCompare(); return; }
    const cmpBox = $("gitCmp"); if (cmpBox) cmpBox.innerHTML = "";
    if (gitHintText) $("gitHint").textContent = gitHintText;
    drawPicker();
    const st = git.status || {}, files = st.files || [], commits = git.commits || [];
    const local = (git.branches || []).filter(b => !b.remote), remote = (git.branches || []).filter(b => b.remote);
    const locked = !!(state?.projects || []).find(p => p.name === project)?.locked;
    const tree = treeOf();
    const fileKey = f => `${f.state}|${f.staged ? 1 : 0}|${f.at || ""}`;
    const fileRows = files.map(f => `<details class="sect gfile" data-path="${esc(f.path)}" data-key="${esc(fileKey(f))}"${
        gitOpenFiles.has(f.path) ? " open" : ""}>
        <summary><span class="t"><code>${esc(f.path)}</code></span>
          <span class="sst${f.state === "conflict" ? " bad" : f.state === "untracked" ? " note" : ""}">${
            esc(f.state)}${f.staged ? " · staged" : ""}</span></summary>
        <div class="body gdiff">${keptBody("file", f.path, fileKey(f), skel("lines", 5))}</div>
        ${locked || tree.barred ? "" : `<div class="body"><div class="actbar">
          ${tree.notMine ? "" : `<button type="button" data-gitaskfile="${esc(f.path)}"
            title="hand this change to the project's Claude session">Send to Claude</button>`}
          <button type="button" class="danger" data-gitdiscard="${esc(f.path)}"
            title="put the file back as the last commit has it; the change is lost">Discard</button>
        </div></div>`}
      </details>`).join("");
    // Adding goes at the top: the commit's form is the section's first
    // band, above the files it will take.
    const treeNote = tree.notMine ? `<div class="sub dim">${esc(tree.owner)}'s uncommitted changes in the project directory${
      tree.barred ? `; only ${esc(tree.owner)} commits or discards them` : ""}</div>` : "";
    const commitBar = files.length && !locked && !tree.barred ? `<div class="addbar gcommitbar ctlrow" data-add="commit">
        <textarea id="gitMsg" class="proseline" rows="1" maxlength="200" placeholder="what changed, for the log"
          aria-label="commit message">${esc(gitMsgDraft)}</textarea>
        <button type="button" class="primary" id="gitCommit"
          title="commit every changed file under your author">Commit all</button>
      </div>` : "";
    const lanes = gitLanes(commits);
    const H = 34, W = 14, lanesN = Math.max(1, ...commits.map(c => c.lane + 1));
    // ago() takes seconds, which is what the server sends. Times a thousand
    // put every commit and branch in the future, and the future is "just now".
    const ago_ = t => t ? ago(t) : "";
    const graph = commits.length ? `<div class="gitgraph" style="--glanes:${lanesN}">
      <svg class="glines" width="${lanesN * W}" height="${commits.length * H}" aria-hidden="true">${
        lanes.edges.map(e => {
          const x1 = e.from.lane * W + W / 2, y1 = e.from.row * H + H / 2;
          const x2 = e.to.lane * W + W / 2, y2 = e.to.row * H + H / 2;
          return `<path d="M${x1} ${y1} C${x1} ${(y1 + y2) / 2} ${x2} ${(y1 + y2) / 2} ${x2} ${y2}" class="gl${e.from.lane % 5}"/>`;
        }).join("")}${
        commits.map((c, i) => `<circle cx="${c.lane * W + W / 2}" cy="${i * H + H / 2}" r="4" class="gn gl${c.lane % 5}${c.sha === gitPick ? " on" : ""}"/>`).join("")}
      </svg>
      <div class="grows">${commits.map(c => `<div class="grow${c.sha === gitPick ? " on" : ""}" data-sha="${esc(c.sha)}" style="height:${H}px">
          <span class="gsub">${c.refs.map(r => `<span class="pill${r.startsWith("HEAD") ? " ok" : ""}">${esc(r.replace(/^HEAD -> /, ""))}</span>`).join("")} ${esc(c.subject)}</span>
          <span class="gmeta">${esc(c.author)} · ${esc(ago_(c.when))} · <code>${esc(c.short)}</code></span>
        </div>`).join("")}</div>
    </div>` : `<div class="empty">no commits yet</div>`;
    // Branches by what there is to do with them, not by date: the one the
    // tree is on; main; work not yet in main, which is what Merge into main
    // is for; branches already in main, which are only there to delete; and,
    // folded, branches the remote has that this tree does not. A remote row
    // that mirrors a local branch is not listed: its counts are on the
    // local row already, and "origin/x" beside "x" read as two branches.
    const main = git.main || "main", host = git.host?.name || "the remote";
    const s_ = n => n === 1 ? "" : "s";
    const vsMain = b => b.name === main ? "the main branch"
      : b.same ? `${b.main_ahead} commit${s_(b.main_ahead)} of its own, and no change ${main} lacks`
      : b.main_ahead ? `${b.main_ahead} commit${s_(b.main_ahead)} not yet in ${main}${b.main_behind ? `, ${b.main_behind} behind it` : ""}`
      : b.main_behind ? `merged into ${main}, ${b.main_behind} behind it` : `same as ${main}`;
    const vsRemote = b => b.merged ? `every commit on it is in ${main}` : `holds work ${main} does not`;
    const vsHost = b => !b.upstream ? "" : (b.ahead || b.behind)
      ? `${b.ahead ? b.ahead + " to push" : ""}${b.ahead && b.behind ? ", " : ""}${b.behind ? b.behind + " to pull" : ""}`
      : "";
    // A branch is its session's (git.py not_yours): another account's is an
    // administrator's to merge, asked each time with the owner named (data-
    // gitwho carries the name to the confirm), and nobody else's, whose row
    // then offers none of it and says whose it is. main is everybody's.
    const theirs = b => !!b.who && b.who !== state?.me;
    const admin = !!state?.admin;
    const barred = b => theirs(b) && !admin;
    const here_ = local.find(x => x.head) || {};
    const whoAttr = b => theirs(b) ? ` data-gitwho="${esc(b.who)}"` : "";
    const whoseLine = b => barred(b) ? `<div class="sub gbwhy">only ${esc(b.who)} merges it</div>` : "";
    // Branches as a table, as GitHub's branches page lays them out (R269
    // step 1, the operator 19 Oct: the section had grown huge): a line a
    // branch, what it is, when it last moved and by whom, how far it stands
    // from main, whose it is, and every verb behind its ⋯. Chips over it
    // narrow it by what there is to do (Active, the default: the tree's
    // branch, main and work not yet in it), with a search beside them; the
    // branches already in main are a count with one Delete until their chip
    // is pressed. A remote row that mirrors a local branch is not listed:
    // its counts are on the local row already.
    const GB_COLS = gitBranchCols(main);
    const sync = b => vsHost(b) ? ` <span class="pill" title="against ${esc(host)}">${esc(vsHost(b))}</span>` : "";
    const pills = b => `${b.head ? ` <span class="pill ok">here</span>` : ""}${b.name === main ? ` <span class="pill">default</span>` : ""}${sync(b)}`;
    // Behind and ahead as GitHub draws them: the two counts either side of
    // a line, each over a bar as long as its share of the longest here.
    const most = Math.max(1, ...local.map(b => Math.max(b.main_ahead || 0, b.main_behind || 0)));
    const bar = n => `<i style="width:${n ? Math.max(6, Math.round(Math.sqrt(n / most) * 100)) : 0}%"></i>`;
    const gab = b => b.remote ? `<span class="gbstate">${esc(vsRemote(b))}</span>`
      : b.name === main ? "" : `<span class="gab" role="img" aria-label="${esc(vsMain(b))}"><span class="l"><b>${b.main_behind || 0}</b>${bar(b.main_behind)}</span><span class="r"><b>${
          b.main_ahead || 0}</b>${bar(b.main_ahead)}</span></span>`;
    const owner = b => b.who ? (b.who === state?.me ? "your session" : `${esc(b.who)}'s session`) : b.remote ? `only on ${esc(host)}` : "";
    // The verbs, each its own item: what Send to Claude asks is the item's,
    // as Merge into main and Switch are.
    const items = b => locked ? [] : b.remote ? [b.merged ? `<button type="button" class="danger"
            data-gitdeleteremote="${esc(b.name)}" title="delete this branch on ${esc(host)}; every commit on it is in ${esc(main)} already">Delete on ${esc(host)}</button>` : ""]
      : [!b.remote && b.name !== main && b.main_ahead ? `<button type="button" data-gitcmp="${esc(b.name)}">Compare with ${esc(main)}</button>` : "",
         b.name === main ? (b.head || barred(here_) ? "" : `<button type="button" data-gitmerge="${esc(main)}"${whoAttr(here_)}
            title="bring ${esc(main)} into ${esc(st.branch || "this branch")}, here, so this branch is up to date with it">Merge ${esc(main)} into here</button>`)
           : !barred(b) && (b.main_ahead || st.branch !== main) && !(b.head && st.branch === main) ? `<button type="button" data-gitmerge="${esc(b.name)}" data-gitinto="${esc(main)}"${whoAttr(b)}
            title="merge ${esc(b.name)} into ${esc(main)}; push ${esc(main)} afterwards">Merge into ${esc(main)}</button>` : "",
         b.head || barred(b) || tree.barred ? "" : `<button type="button" data-gitswitch="${esc(b.name)}" title="put the tree on this branch">Switch to it</button>`,
         ...(b.name === main ? [] : [...(barred(b) ? [] : [["merge", `Ask Claude to merge it into ${esc(main)}`], ["rebase", `Ask Claude to rebase it onto ${esc(main)}`]]),
              ["review", "Ask Claude to review it"]].map(([k, w]) => `<button type="button" data-gitaskbranch="${esc(b.name)}" data-gitaskkind="${k}"${
              k === "review" ? "" : whoAttr(b)} title="hand this branch to the project's Claude session with this ask">${w}</button>`)),
         b.head || b.name === main || barred(b) ? "" : `<button type="button" class="danger"
            data-gitdelete="${esc(b.name)}" title="${b.merged ? "delete the branch; everything on it is in " + esc(main) : "delete the branch: refused while it holds commits no other branch has"}">Delete</button>`];
    // A branch with work main lacks opens its comparison, a page of its own,
    // from its line or its ⋯.
    const kind = b => b.remote ? "remote" : b.head || b.name === main ? "active" : b.merged ? "merged" : "active";
    const branchRow = b => `<div class="row gbranch${!b.remote && b.name !== main && b.main_ahead ? " gopens" : ""}" data-branch="${esc(b.name)}" data-kind="${kind(b)}"${
        b.who === state?.me ? " data-mine" : ""}>${tblLine(GB_COLS, [`<code>${esc(b.name)}</code>${pills(b)}`,
        `${esc(ago_(b.when))}${b.author ? ` <span class="dim">· ${esc(b.author)}</span>` : ""}`, gab(b), owner(b),
        `<span class="actbar">${actMore(items(b), true)}</span>`])}${whoseLine(b)}</div>`;
    const here = local.filter(b => b.head), mainRow = local.filter(b => b.name === main && !b.head);
    const waiting = local.filter(b => !b.head && b.name !== main && !b.merged);
    const finished = local.filter(b => !b.head && b.name !== main && b.merged);
    const clearable = finished.filter(b => !theirs(b));   // another account's is theirs to delete
    const remoteOnly = remote.filter(r => !local.some(l => r.name.endsWith("/" + l.name)));
    const every = [...here, ...mainRow, ...waiting, ...finished, ...remoteOnly];
    const counts = {active: here.length + mainRow.length + waiting.length, mine: every.filter(b => b.who === state?.me).length,
                    merged: finished.length, remote: remoteOnly.length};
    if (gitBranchChip && !counts[gitBranchChip]) gitBranchChip = counts.active ? "active" : "";
    const branchChips = chipButtons([{key: "active", label: "Active", count: counts.active}, {key: "mine", label: "Yours", count: counts.mine},
      {key: "merged", label: `In ${main}`, count: counts.merged}, {key: "remote", label: `Only on ${host}`, count: counts.remote}], gitBranchChip, "data-gbchip", every.length);
    const mergedBar = finished.length && !locked && clearable.length ? `<div class="actbar gmerged" data-kind="merged-bar">
          <span class="state">${finished.length} branch${finished.length === 1 ? " is" : "es are"} already in ${esc(main)}: nothing on ${
            finished.length === 1 ? "it" : "them"} is missing from it</span>
          ${gitBranchChip === "merged" ? "" : `<button type="button" data-gbchip="merged">Show</button>`}
          <button type="button" class="danger" data-gitdeletemerged="${esc(clearable.map(b => b.name).join(" "))}"
            title="delete every branch already in ${esc(main)}">Delete ${clearable.length === 1 ? "it" : `all ${clearable.length}`}</button>
        </div>` : "";
    const branchRows = (every.length > 1 ? `<div class="field lfilter gbfilter">${branchChips ? `<div class="chips">${branchChips}</div>` : ""}
        <input id="gitBranchFind" type="search" maxlength="80" autocomplete="off" value="${esc(gitBranchFind)}"
          placeholder="find a branch" aria-label="find a branch"></div>` : "")
      + `<div class="sub dim">${esc(host)} holds a copy that only Push and Pull touch.</div>`
      + tblWrap(GB_COLS, every.map(branchRow).join(""), "gbranches")
      + `<div class="empty gbnone" hidden>no branch matches</div>` + mergedBar;
    // Conflicts stop everything else, so they are said first, with the one
    // button that helps: the merge in progress handed to the session.
    const conflicts = files.filter(f => f.state === "conflict");
    const conflictBar = conflicts.length && !locked ? `<div class="actbar gconflict">
        <span class="state bad">${conflicts.length} file${conflicts.length === 1 ? "" : "s"} in conflict: the merge is not finished</span>
        <button type="button" class="primary" data-gitask="conflicts"
          title="hand the merge to the project's Claude session to finish">Resolve with Claude</button>
      </div>` : "";
    // What a session may do with the remote (roadmap R36): the answers,
    // staged until Apply like every setting on the page. Enforced on the
    // relay; a local commit or merge cannot be forbidden, and the bar says so.
    // The third is whether a push with lines that look sensitive waits on
    // the bell for a person (R219) or goes without the hold.
    const pol = {...((state?.projects || []).find(p => p.name === project)?.prefs?.gitpol || {}), ...gitPolDraft};
    const polDirty = Object.keys(gitPolDraft).length > 0;
    const policy = locked ? "" : `<div class="row stack2 gpolicy"><div class="grow">
        <div class="prefrow ctlrow">
          <label class="pick">Push its branches <select data-gitpol="push">${["allow", "deny"].map(o =>
            `<option value="${o}"${(pol.push || "allow") === o ? " selected" : ""}>${o}</option>`).join("")}</select></label>
          <label class="pick">Push to ${esc(git.main || "main")} <select data-gitpol="main">${["allow", "deny"].map(o =>
            `<option value="${o}"${(pol.main || "deny") === o ? " selected" : ""}>${o}</option>`).join("")}</select></label>
          <label class="pick">Hold a push that looks sensitive <select data-gitpol="scan">${["hold", "off"].map(o =>
            `<option value="${o}"${(pol.scan || "hold") === o ? " selected" : ""}>${o}</option>`).join("")}</select></label>
        </div>
        <div class="actbar">
          <span class="state">its own branches, one at a time ${helpIcon("Applies to pushes only. Tags, deletions and remote-only branches stay yours; commits and merges here are always allowed.")}</span>
          <button type="button" id="gitPolApply"${polDirty ? "" : " disabled"}>Apply</button>
        </div></div></div>`;
    body.innerHTML = docSection("git", "changes", gitTitle("changes"), files.length ? String(files.length) : "none",
        conflictBar + (files.length ? treeNote : "") + commitBar + (files.length ? fileRows : `<div class="empty">nothing changed since the last commit</div>`))
      + docSection("git", "history", gitTitle("history"), commits.length ? `${commits.length}${commits.length >= 100 ? "+" : ""}` : "none",
        graph + `<div id="gitDetail"${gitPick ? "" : " hidden"}></div>`)
      + docSection("git", "branches", gitTitle("branches"), String(local.length), (branchRows || `<div class="empty">no branches</div>`))
      + ciSection()
      + (policy ? docSection("git", "policy", gitTitle("policy"), `${pol.push || "allow"} · ${pol.main || "deny"}${pol.scan === "off" ? " · unheld" : ""}`, policy) : "");
    wireSections(body);
    wireMore(body);
    gitBranchShow(body);
    body.querySelectorAll("[data-gbchip]").forEach(b => b.onclick = () => { gitBranchChip = b.dataset.gbchip; drawGit(); });
    const bf = $("gitBranchFind");
    if (bf) bf.oninput = () => { gitBranchFind = bf.value; gitBranchShow(body); };
    // A branch with work main lacks opens its comparison from its ⋯ or from
    // a press anywhere on its line that is not a button.
    body.querySelectorAll("[data-gitcmp]").forEach(b => b.onclick = () => { closeMore(); gitGoCompare(b.dataset.gitcmp); });
    body.querySelectorAll(".gbranch.gopens > .tline").forEach(l => l.onclick = e => {
      if (!e.target.closest("button, a, input, select, .more")) gitGoCompare(l.parentElement.dataset.branch);
    });
    body.querySelectorAll("[data-cifix]").forEach(b => b.onclick = () => gitAct("ci-fix", {where: b.dataset.cifix}, b, "Fixing"));
    const cl = $("gitCiLook");
    if (cl) cl.onclick = async () => {
      busy(cl, "Looking");
      try{
        const j = await (await postJSON("/api/ci-watch", {project})).json();
        if (j.error) notify(j.error, true);
        else { git.ci = j; drawGit(); }
      }catch(e){ notify("could not reach the controller: " + e, true); }
      finally{ if (cl.isConnected) unbusy(cl, "Look now"); }
    };
    body.querySelectorAll("[data-gitpol]").forEach(sel => sel.onchange = () => {
      const saved = (state?.projects || []).find(p => p.name === project)?.prefs?.gitpol || {};
      if (sel.value === (saved[sel.dataset.gitpol] || GITPOL_DEFAULT[sel.dataset.gitpol])) delete gitPolDraft[sel.dataset.gitpol];
      else gitPolDraft[sel.dataset.gitpol] = sel.value;
      const b = $("gitPolApply"); if (b) b.disabled = !Object.keys(gitPolDraft).length;
    });
    const pa = $("gitPolApply");
    if (pa) pa.onclick = async () => {
      busy(pa, "Applying");
      try{
        const r = await postJSON("/api/prefs", {project, gitpol: {...pol, ...gitPolDraft}});
        const j = await r.json();
        if (j.error) return notify(j.error, true);
        gitPolDraft = {};
        notify("saved");
        refresh(); drawGit();
      }catch(e){ notify("policy: " + e, true); }
      finally{ if (pa.isConnected) unbusy(pa, "Apply"); }
    };
    body.querySelectorAll("[data-gitask]").forEach(b => b.onclick = () => gitAsk(b.dataset.gitask, {}, b));
    const msg = $("gitMsg");
    if (msg){
      msg.oninput = () => { gitMsgDraft = msg.value; };
      msg.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); $("gitCommit")?.click(); } };
    }
    const cm = $("gitCommit");
    if (cm) cm.onclick = async () => {
      if (!gitMsgDraft.trim()) return notify("a commit needs a message", true);
      const j = await gitAct("commit", {message: gitMsgDraft}, gitBusy(cm), "Committing");
      if (j && j.ok) gitMsgDraft = "";
    };
    body.querySelectorAll("[data-gitdiscard]").forEach(b => b.onclick = () => {
      const path = b.dataset.gitdiscard;
      if (confirm(`Discard the changes to ${path}?\n\nIt goes back to the last commit; the change is lost.`))
        gitAct("discard", {path}, gitBusy(b), "Discarding");
    });
    body.querySelectorAll("[data-gitswitch]").forEach(b => b.onclick = () =>
      gitAct("switch", {name: b.dataset.gitswitch}, gitBusy(b), "Switching"));
    wireBranchActs(body);
    body.querySelectorAll("[data-gitdeleteremote]").forEach(b => b.onclick = () => {
      const name = b.dataset.gitdeleteremote;
      if (!confirm(`Delete ${name} on ${git.host?.name || "the remote"}? Every commit on it is in ${
          git.main || "main"} already, so nothing is lost; the branch stops being listed there.`)) return;
      gitAct("delete-remote", {name}, gitBusy(b), "Deleting");
    });
    body.querySelectorAll("[data-gitdeletemerged]").forEach(b => b.onclick = async () => {
      const names = b.dataset.gitdeletemerged.split(" ").filter(Boolean);
      if (!confirm(`Delete ${names.length === 1 ? names[0] : names.length + " branches"}? Everything on ${
          names.length === 1 ? "it" : "them"} is in ${git.main || "main"} already.`)) return;
      busy(b, "Deleting");
      for (const name of names) await gitAct("delete", {name});
    });
    body.querySelectorAll("[data-gitaskfile]").forEach(b => b.onclick = () =>
      gitAsk("diff", {path: b.dataset.gitaskfile}, gitBusy(b)));
    body.querySelectorAll("[data-gitdelete]").forEach(b => b.onclick = () => {
      const name = b.dataset.gitdelete;
      if (confirm(`Delete the branch ${name}?`)) gitAct("delete", {name}, gitBusy(b), "Deleting");
    });
    body.querySelectorAll(".gfile").forEach(d => {
      d.addEventListener("toggle", () => {
        if (d.open) gitOpenFiles.add(d.dataset.path); else gitOpenFiles.delete(d.dataset.path);
        if (d.open && d.querySelector(".loading")) loadGitFile(d);
      });
      if (d.open && d.querySelector(".loading")) loadGitFile(d);
    });
    body.querySelectorAll(".grow[data-sha]").forEach(r => r.onclick = () => {
      gitPick = gitPick === r.dataset.sha ? "" : r.dataset.sha;
      gitReveal = gitPick;
      drawGit();                 // which loads the picked commit's detail
    });
    if (gitPick) loadGitCommit(gitPick);
  }

  function loadGitFile(d){
    const path = d.dataset.path;
    return keptLoad("file", d, ".gdiff", path,
      "/api/git?project=" + encodeURIComponent(project) + "&what=diff&path=" + encodeURIComponent(path), j => renderDiff(j.diff));
  }

  // The branch the tree is on, in the view's head row as a picker, as
  // GitHub's (R269 step 3): a press opens the local branches with a box to
  // find one, a press on one switches the tree to it, and a name nobody has
  // yet offers to create it from the commit the tree is on and switch to it.
  // Where the tree is not the reader's to move (another account's, a
  // locked project) the branch is said and nothing opens.
  function drawPicker(){
    const box = $("gitPicker");
    if (!box || !git || git.error) return;
    const st = git.status || {}, cur = st.branch || "";
    const local = (git.branches || []).filter(b => !b.remote);
    const locked = !!(state?.projects || []).find(p => p.name === project)?.locked;
    const still = locked || treeOf().barred || !cur;
    box.hidden = !cur;
    const label = `<span class="gbpickic" aria-hidden="true">${BRANCH_ICON}</span><span class="gbpickname">${esc(cur)}</span>`;
    if (still){ box.innerHTML = `<span class="gbpickb still">${label}</span>`; return; }
    // A redraw while the picker is open (a commit landing from elsewhere)
    // keeps it open with what was typed and the caret where it was.
    const old = box.querySelector("#gitPickFind"), was = old?.value || "";
    const typing = !!old && document.activeElement === old, caret = typing ? old.selectionStart : null;
    const open = !!box.querySelector(".gbpickmenu:not([hidden])");
    box.innerHTML = `<button type="button" class="gbpickb" data-menuopen aria-haspopup="menu" aria-expanded="${open}"
        aria-label="the branch the tree is on: ${esc(cur)}; press to switch or create one">${label}<span class="gbpickcaret" aria-hidden="true">▾</span></button>
      <div class="actmenu gbpickmenu" role="menu"${open ? "" : " hidden"}>
        <input id="gitPickFind" type="search" maxlength="120" autocomplete="off" spellcheck="false" value="${esc(was)}"
          placeholder="find or create a branch" aria-label="find or create a branch">
        <div class="gbpicklist">${local.map(b => `<button type="button" role="menuitem" data-gitpick="${esc(b.name)}"${
          b.head ? ` class="on" aria-current="true"` : ""}>${esc(b.name)}</button>`).join("")}</div>
        <button type="button" role="menuitem" class="gbpicknew" data-gitpicknew hidden></button>
      </div>`;
    const btn = box.querySelector(".gbpickb"), menu = box.querySelector(".gbpickmenu"), find = box.querySelector("#gitPickFind");
    const sift = () => {
      const q = find.value.trim(), ql = q.toLowerCase();
      box.querySelectorAll("[data-gitpick]").forEach(b => { b.hidden = !!ql && !b.dataset.gitpick.toLowerCase().includes(ql); });
      const make = box.querySelector("[data-gitpicknew]"), have = local.some(b => b.name === q);
      make.hidden = !q || have;
      make.innerHTML = q ? `Create branch <b>${esc(q)}</b> from <b>${esc(cur)}</b>` : "";
    };
    sift();
    if (open) floatAt(menu, btn);
    if (typing){ find.focus(); try{ find.setSelectionRange(caret, caret); }catch(e){ /* not a text box */ } }
    btn.onclick = () => {
      const opening = menu.hidden;
      closeMore();
      if (!opening) return;
      // Each opening starts on the whole list, the box empty.
      find.value = ""; sift();
      menu.hidden = false; btn.setAttribute("aria-expanded", "true");
      floatAt(menu, btn);
      find.focus();
    };
    find.oninput = sift;
    find.onkeydown = e => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const q = find.value.trim();
      const hit = local.find(b => b.name === q) || [...box.querySelectorAll("[data-gitpick]")].find(b => !b.hidden && q);
      if (hit) (hit.dataset ? hit : box.querySelector(`[data-gitpick="${CSS.escape(hit.name)}"]`))?.click();
      else if (q) box.querySelector("[data-gitpicknew]").click();
    };
    box.querySelectorAll("[data-gitpick]").forEach(b => b.onclick = () => {
      closeMore();
      if (b.dataset.gitpick !== cur) gitAct("switch", {name: b.dataset.gitpick}, gitBusy(btn), "Switching");
    });
    box.querySelector("[data-gitpicknew]").onclick = async () => {
      const name = find.value.trim();
      closeMore();
      if (name) await gitAct("branch", {name, switch: true}, gitBusy(btn), "Creating");
    };
  }

  // A branch's Merge and its asks of Claude, on the branches table and on a
  // comparison's page alike.
  // No confirmation: a merge makes a commit rather than destroying one, and
  // the row says which way round it goes. What it can leave behind is a
  // conflict, and the Changes section is already the place that says so.
  // Another account's branch, merged in or merged into, is asked about
  // every time with the owner named; the answer rides as `confirmed`. A
  // merge from a comparison's page returns to the branches once it lands.
  function wireBranchActs(root){
    const main = git?.main || "main", here = git?.status?.branch || "this branch";
    root.querySelectorAll("[data-gitmerge]").forEach(b => b.onclick = async () => {
      const name = b.dataset.gitmerge, into = b.dataset.gitinto || here;
      const who = b.dataset.gitwho, their = b.dataset.gitinto ? name : into;
      if (who && !confirm(`Merge ${name} into ${into}?\n\n${their} is ${who}'s session's branch.`)) return;
      const j = await gitAct("merge", {name, ...(b.dataset.gitinto ? {into: b.dataset.gitinto} : {}), ...(who ? {confirmed: true} : {})},
             gitBusy(b), "Merging");
      if (j?.ok && gitCmp === name) gitGoCompare("");
    });
    root.querySelectorAll("[data-gitaskbranch]").forEach(b => b.onclick = () => {
      const kind = b.dataset.gitaskkind || "merge";
      const name = b.dataset.gitaskbranch, who = b.dataset.gitwho, moves = kind === "merge" || kind === "rebase";
      if (who && moves && !confirm(`Ask Claude to ${kind} ${name} ${kind === "merge" ? "into" : "onto"} ${main}?\n\n${name} is ${who}'s session's branch.`)) return;
      gitAsk(kind, {branch: name, ...(who && moves ? {confirmed: true} : {})}, gitBusy(b));
    });
  }

  // ---- a branch against main, its own page (R269 step 2) -------------------
  // What a pull request page shows before its button: the commits main
  // lacks, the files changed with what each adds and takes away, each
  // file's diff, and Merge at the foot. Its address names the branch, so a
  // link lands on it and Back returns to the branches.
  function gitGoCompare(name){
    // Back to the branches is a move of its own, not the browser's Back: a
    // comparison reached from a link has nothing before it to go back to.
    navPush(() => { gitCmp = name; drawGit(); });
    $("gitCmp")?.closest(".nbview")?.scrollIntoView?.({block: "start"});
  }
  nb.gitPage = () => gitCmp;
  nb.gitAt = name => { if ((name || "") !== gitCmp){ gitCmp = name || ""; if (git) drawGit(); } };
  async function loadCompare(name, key){
    try{
      const j = await (await fetch("/api/git?project=" + encodeURIComponent(project) + "&what=compare&branch=" + encodeURIComponent(name))).json();
      gitCmpData = {name, key, j};
    }catch(e){ gitCmpData = {name, key, j: {error: String(e)}}; }
    if (gitCmp === name) drawCompare();
  }
  function drawCompare(){
    const box = $("gitCmp");
    if (!box || !git || git.error) return;
    const name = gitCmp, main = git.main || "main", host = git.host?.name || "the remote";
    const all = git.branches || [], b = all.find(x => !x.remote && x.name === name);
    const mainB = all.find(x => !x.remote && x.name === main);
    const key = `${b?.short || ""}|${mainB?.short || ""}`;
    // The head says where this is, Branches a link to the view's own
    // address (a pointer to a page is a link to its address), as GitHub's
    // compare page names the two branches over it.
    $("gitHint").innerHTML = `<a href="${esc(routeOf({kind: "notebook", arg: project}).replace(/\/compare\/.*$/, ""))}" data-gitcmpback>Branches</a> › ${esc(name)} into ${esc(main)}`;
    const back = "";
    if (!b){
      box.innerHTML = back + `<div class="field"><div class="empty">no branch called ${esc(name)} here now</div></div>`;
            return;
    }
    if (gitCmpData?.name !== name || gitCmpData.key !== key){
      if (!gitCmpData || gitCmpData.name !== name) box.innerHTML = back + docSection("git", "cmp-commits", "Commits", "", skRows(3))
        + docSection("git", "cmp-files", "Files changed", "", skRows(3));
            loadCompare(name, key);
      return;
    }
    const j = gitCmpData.j;
    if (j.error){
      box.innerHTML = back + `<div class="field"><div class="hint bad">${esc(j.error)}</div></div>`;
            return;
    }
    const s_ = n => n === 1 ? "" : "s";
    const commits = j.commits || [], files = j.files || [];
    const added = files.reduce((n, f) => n + (f.added || 0), 0), removed = files.reduce((n, f) => n + (f.removed || 0), 0);
    const locked = !!(state?.projects || []).find(p => p.name === project)?.locked;
    const theirs = !!b.who && b.who !== state?.me, barred = theirs && !state?.admin;
    // The commits as the history draws them, newest first; the files as a
    // list with their counts, then each one's diff.
    const commitRows = commits.length ? commits.map(c => `<div class="row gcmpcommit"><div class="grow">
        <div class="name">${esc(c.subject)}</div>
        <div class="sub">${esc(c.author)} · ${esc(ago(c.when))} · <code>${esc(c.short)}</code></div></div></div>`).join("")
      : `<div class="empty">no commit ${esc(main)} lacks</div>`;
    const fileRows = files.length ? `<div class="gcmpfiles">${files.map(f => `<div class="gcmpfile"><code>${esc(f.path)}</code>${
        f.added != null ? `<span class="gadd">+${f.added}</span><span class="gdel">−${f.removed}</span>` : `<span class="dim">binary</span>`}</div>`).join("")}</div>`
        + renderDiff(j.diff || "")
      : `<div class="empty">no file changed</div>`;
    const ahead = b.main_behind ? `, ${b.main_behind} commit${s_(b.main_behind)} behind ${esc(main)}` : "";
    const foot = locked ? "" : `<div class="field actbar gcmpfoot">
        <span class="state${barred ? " bad" : ""}">${barred ? `only ${esc(b.who)} merges it` : b.same
          ? `nothing here that ${esc(main)} does not already have`
          : `${commits.length} commit${s_(commits.length)} into ${esc(main)}${ahead}; push ${esc(main)} to ${esc(host)} afterwards`}</span>
        <button type="button" data-gitaskbranch="${esc(name)}" data-gitaskkind="review"
          title="hand this branch to the project's Claude session to review">Ask Claude to review it</button>
        ${barred || !commits.length ? "" : `<button type="button" class="primary" data-gitmerge="${esc(name)}" data-gitinto="${esc(main)}"${
          theirs ? ` data-gitwho="${esc(b.who)}"` : ""} title="merge ${esc(name)} into ${esc(main)}">Merge into ${esc(main)}</button>`}
      </div>`;
    box.innerHTML = back
      + `<div class="field gcmpsum"><div class="sub">${esc(name)}${b.who ? `, ${b.who === state?.me ? "your session's" : `${esc(b.who)}'s session's`}` : ""}: ${
          commits.length} commit${s_(commits.length)}, ${files.length} file${s_(files.length)} changed, <span class="gadd">+${added}</span> <span class="gdel">−${removed}</span></div></div>`
      + docSection("git", "cmp-commits", "Commits", String(commits.length), commitRows)
      + docSection("git", "cmp-files", "Files changed", String(files.length), fileRows)
      + foot;
    wireSections(box);
        wireBranchActs(box);
  }

  async function loadGitCommit(sha){
    let box = $("gitDetail");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = `${skel("lines", 6)}`;
    try{
      const r = await fetch("/api/git?project=" + encodeURIComponent(project) + "&what=show&sha=" + encodeURIComponent(sha));
      const c = await r.json();
      if (sha !== gitPick) return;               // moved on meanwhile
      // The box on the page NOW: a redraw while the answer was on its way
      // (a commit landing, the poll) replaced it, and writing into the one
      // resolved above put the detail into a detached element (B256).
      box = $("gitDetail");
      if (!box) return;
      box.hidden = false;
      if (c.error){ box.innerHTML = `<div class="hint bad">${esc(c.error)}</div>`; return; }
      const when = c.when ? fmtTime(c.when * 1000) : "";
      box.innerHTML = `<div class="gcommit">
        <div class="name"><code>${esc(c.short)}</code> ${esc(c.message.split("\n")[0])}</div>
        <div class="sub">${esc(c.author)} &lt;${esc(c.email)}&gt; · ${esc(when)}${
          c.parents.length > 1 ? " · merge" : ""}${c.refs.length ? " · " + c.refs.map(esc).join(", ") : ""}</div>
        ${c.message.includes("\n") ? `<pre class="gmsg">${esc(c.message.split("\n").slice(1).join("\n").trim())}</pre>` : ""}
        <div class="sub">${c.files.length} file${c.files.length === 1 ? "" : "s"}: ${c.files.map(f =>
          `<code>${esc(f.path)}</code>${f.added != null ? ` <span class="gadd">+${f.added}</span> <span class="gdel">−${f.removed}</span>` : ""}`).join(", ")}</div>
        ${(state?.projects || []).find(p => p.name === project)?.locked ? "" : `<div class="actbar">
          ${treeOf().barred ? "" : `<span class="state">revert makes a new commit undoing this one; a branch starts from it</span>`}
          <select data-gitaskkind aria-label="what to ask"><option value="review">review</option>
            <option value="explain">explain</option><option value="revert">revert</option></select>
          <button type="button" data-gitaskcommit="${esc(c.sha)}"
            title="hand this commit to the project's Claude session with the ask picked">Send to Claude</button>
          ${treeOf().barred ? "" : `<button type="button" data-gitbranchat="${esc(c.sha)}" title="a new branch starting at this commit">Branch here</button>
          <button type="button" data-gitrevert="${esc(c.sha)}" title="a new commit that undoes this one; nothing is rewritten">Revert</button>`}
        </div>`}
        ${renderDiff(c.diff)}
      </div>`;
      revealCommit(box, sha);
      box.querySelectorAll("[data-gitrevert]").forEach(b => b.onclick = () => {
        if (confirm(`Revert ${c.short}: ${c.message.split("\n")[0]}?\n\nA new commit undoes it; the history keeps both.`))
          gitAct("revert", {sha: b.dataset.gitrevert}, gitBusy(b), "Reverting");
      });
      box.querySelectorAll("[data-gitaskcommit]").forEach(b => b.onclick = () =>
        gitAsk(box.querySelector("[data-gitaskkind]")?.value || "review", {sha: b.dataset.gitaskcommit}, gitBusy(b)));
      box.querySelectorAll("[data-gitbranchat]").forEach(b => b.onclick = async () => {
        const name = await askInline(b.closest(".actbar") || b, {label: `A branch starting at ${c.short}: its name`, ok: "Make the branch"});
        if (name) gitAct("branch", {name, at: b.dataset.gitbranchat, switch: true}, gitBusy(b), "Creating");
      });
    }catch(e){ box.innerHTML = `<div class="hint bad">${esc(String(e))}</div>`; revealCommit(box, sha); }
  }

  // Down to the picked commit's detail, once, when a click picked it.
  function revealCommit(box, sha){
    if (gitReveal !== sha || !box.isConnected) return;
    gitReveal = "";
    // A jump, the way the page scrolls elsewhere: a smooth scroll can be cut
    // short by the redraw a git revision brings, leaving the change half
    // way down.
    box.scrollIntoView({block: "start"});
  }

  return {loadGit};
}
