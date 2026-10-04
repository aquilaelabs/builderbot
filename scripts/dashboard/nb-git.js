// The notebook's Git view: the repository read out, its branches, its
// commits, the policy that says what a session may push, and Send to Claude.
// One classic script beside index.html, the shape tab-*.js has (docs/nodes.md
// §13): same page, same global scope, one file per notebook view (R60).
//
// A factory rather than a script that runs: makeNotebook calls it per
// notebook with the notebook's element lookup, its state object and its
// project, and takes back the one function the rest of the notebook calls.

"use strict";

function nbGitView({$, nb, project}){
  // ---- git -----------------------------------------------------------------
  // The repository, read out (roadmap R36 step 1). Fetched on open and on
  // the git revision (the tree's HEAD log moving) never on the poll: a
  // history is a git call per question. What is open stays open across a
  // redraw: the commit picked and the files unfolded are kept by sha and
  // path, not by position.
  let git = null, gitPick = "", gitOpenFiles = new Set(), gitOpenCmp = new Set();
  // The commit a click picked, until its detail has drawn and been scrolled
  // to: the detail sits under the whole history, so a long one leaves the
  // change below the fold. A redraw from a poll leaves the page where it is.
  let gitReveal = "";
  let gitMsgDraft = "", gitBranchDraft = "";      // typed and not sent, across redraws
  let gitPolDraft = {};                            // the policy picked and not applied

  // Send to Claude: the thing picked and what is asked of it, composed on
  // the controller and typed into the project's session the way a roadmap
  // step arrives; then the tab, so the answer is watched.
  async function gitAsk(kind, args, btn){
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
    hint.textContent = `${tree.notMine ? `${tree.owner}'s working tree, ` : ""}on ${st.branch || "no branch"} · ${files.length
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
    const rows = fs.map(f => `<div class="actbar"><span class="state ${f.sev === "bad" ? "bad" : f.sev === "warn" ? "warn" : ""}">${
        esc(word[f.kind] || f.kind)}: ${esc(f.text)} <code>${esc(f.where || "")}</code></span></div>`).join("");
    const run = ci.run?.id ? ` The newest run on ${esc(ci.run.branch)} ${esc(ci.run.ended || "ended " + ci.run.conclusion)}.` : "";
    const body = `<div class="sub dim">${ci.at ? `Looked ${esc(ago(ci.at))}${ci.repo ? ` at ${esc(ci.repo)} on GitHub` : ""}.${run}` :
        "Not looked at yet."} Looked at once a day and when the project is linked; a session reads a run with bb ci-log.</div>${
      ci.error ? `<div class="sub bad">${esc(ci.error)}</div>` : ""}${rows}
      <div class="actbar"><button type="button" id="gitCiLook">Look now</button></div>`;
    return docSection("git", "ci", "CI", status, body, {cls, open: red});
  }

  function drawGit(){
    const body = $("gitBody");
    if (!git || git.error) return;
    const st = git.status || {}, files = st.files || [], commits = git.commits || [];
    const local = (git.branches || []).filter(b => !b.remote), remote = (git.branches || []).filter(b => b.remote);
    const locked = !!(state?.projects || []).find(p => p.name === project)?.locked;
    const tree = treeOf();
    const fileRows = files.map(f => `<details class="sect gfile" data-path="${esc(f.path)}"${
        gitOpenFiles.has(f.path) ? " open" : ""}>
        <summary><span class="t"><code>${esc(f.path)}</code></span>
          <span class="sst${f.state === "conflict" ? " bad" : f.state === "untracked" ? " note" : ""}">${
            esc(f.state)}${f.staged ? " · staged" : ""}</span></summary>
        <div class="body gdiff"><div class="loading">loading…</div></div>
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
    const commitBar = files.length && !locked && !tree.barred ? `<div class="addbar gcommitbar" data-add="commit">
        <textarea id="gitMsg" class="proseline" rows="1" maxlength="200" placeholder="what changed, for the log"
          aria-label="commit message">${esc(gitMsgDraft)}</textarea>
        <button type="button" class="primary" id="gitCommit"
          title="commit every changed file under your author">Commit all</button>
      </div>` : "";
    const branchBar = locked || tree.barred ? "" : `<div class="addbar gbranchbar" data-add="branch">
        <input id="gitNewBranch" maxlength="120" autocomplete="off" spellcheck="false"
          placeholder="new branch, from the commit the tree is on" aria-label="new branch name" value="${esc(gitBranchDraft)}">
        <button type="button" id="gitBranchGo">New branch</button>
      </div>`;
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
      ? `${b.ahead ? b.ahead + " to push" : ""}${b.ahead && b.behind ? ", " : ""}${b.behind ? b.behind + " to pull" : ""} (${host})`
      : `in step with ${host}`;
    // A branch is its session's (git.py not_yours): another account's is an
    // administrator's to merge, asked each time with the owner named (data-
    // gitwho carries the name to the confirm), and nobody else's, whose row
    // then offers none of it and says whose it is. main is everybody's.
    const theirs = b => !!b.who && b.who !== state?.me;
    const admin = !!state?.admin;
    const barred = b => theirs(b) && !admin;
    const here_ = local.find(x => x.head) || {};
    const whoAttr = b => theirs(b) ? ` data-gitwho="${esc(b.who)}"` : "";
    const whoseLine = b => barred(b) ? `<div class="sub">only ${esc(b.who)} merges it</div>` : "";
    const pills = b => `${b.head ? ` <span class="pill ok">here</span>` : ""}${
            b.who ? ` <span class="pill">${b.who === state?.me ? "your session" : `${esc(b.who)}'s session`}</span>` : ""}${
            b.remote ? ` <span class="pill">only on ${esc(host)}</span>` : ""}`;
    const acts = b => locked ? "" : b.remote ? (b.merged ? `<span class="acts"><button type="button" class="danger"
            data-gitdeleteremote="${esc(b.name)}" title="delete this branch on ${esc(host)}; every commit on it is in ${esc(main)} already">Delete on ${esc(host)}</button></span>` : "")
      : `<span class="acts">${b.name === main ? "" : `<select data-gitaskkind aria-label="what to ask">${barred(b) ? "" : `
            <option value="merge">merge into ${esc(main)}</option><option value="rebase">rebase onto ${esc(main)}</option>`}
            <option value="review">review</option></select><button type="button" data-gitaskbranch="${esc(b.name)}"
            title="hand this branch to the project's Claude session with the ask picked"${whoAttr(b)}>Send to Claude</button>`}${
            b.name === main ? (b.head || barred(here_) ? "" : `<button type="button" data-gitmerge="${esc(main)}"${whoAttr(here_)}
            title="bring ${esc(main)} into ${esc(st.branch || "this branch")}, here, so this branch is up to date with it">Merge ${esc(main)} into here</button>`)
            : !barred(b) && (b.main_ahead || st.branch !== main) && !(b.head && st.branch === main) ? `<button type="button" data-gitmerge="${esc(b.name)}" data-gitinto="${esc(main)}"${whoAttr(b)}
            title="merge ${esc(b.name)} into ${esc(main)}; push ${esc(main)} afterwards">Merge into ${esc(main)}</button>` : ""}${
            b.head || barred(b) || tree.barred ? "" : `<button type="button"
            data-gitswitch="${esc(b.name)}" title="put the tree on this branch">Switch</button>`}${
            b.head || b.name === main || barred(b) ? "" : `<button type="button" class="danger"
            data-gitdelete="${esc(b.name)}" title="${b.merged ? "delete the branch; everything on it is in " + esc(main) : "delete the branch: refused while it holds commits no other branch has"}">Delete</button>`}</span>`;
    // A branch with work main lacks is a row you open: its commits and the
    // diff main would take, which is what a pull request page shows before
    // its button, so that page is not needed to look before Merge into main.
    const branchRow = b => !b.remote && b.name !== main && b.main_ahead ? `<details class="sect gbranch gcmp" data-branch="${esc(b.name)}"${
        gitOpenCmp.has(b.name) ? " open" : ""}>
        <summary><span class="t"><code>${esc(b.name)}</code>${pills(b)}</span>
          <span class="sst">${esc(vsMain(b))}</span></summary>
        <div class="body"><div class="sub">${[vsHost(b), `${esc(b.short)} · ${esc(ago_(b.when))}`].filter(Boolean).join(" · ")}</div>
          ${whoseLine(b)}
          <div class="gcmpbody"><div class="loading">loading…</div></div>
          ${acts(b)}</div>
      </details>` : `<div class="row gbranch">
        <div class="grow"><div class="name"><code>${esc(b.name)}</code>${pills(b)}</div>
          <div class="sub">${[b.remote ? vsRemote(b) : vsMain(b), vsHost(b),
            `${esc(b.short)} · ${esc(ago_(b.when))}`].filter(Boolean).join(" · ")}</div>${whoseLine(b)}</div>
        ${acts(b)}
      </div>`;
    const here = local.filter(b => b.head), mainRow = local.filter(b => b.name === main && !b.head);
    const waiting = local.filter(b => !b.head && b.name !== main && !b.merged);
    const finished = local.filter(b => !b.head && b.name !== main && b.merged);
    const clearable = finished.filter(b => !theirs(b));   // another account's is theirs to delete
    const remoteOnly = remote.filter(r => !local.some(l => r.name.endsWith("/" + l.name)));
    const group = (label, rows) => rows.length ? `<div class="sub dim ggroup">${label}</div>` + rows.map(branchRow).join("") : "";
    const branchRows = `<div class="sub dim">${esc(host)} holds a copy that only Push and Pull touch.</div>`
      + [...here, ...mainRow].map(branchRow).join("")
      + group(`not yet in ${esc(main)}`, waiting)
      + (finished.length ? group(`already in ${esc(main)}`, finished) + (locked || !clearable.length ? "" : `<div class="actbar gmerged">
          <span class="state">nothing on ${clearable.length === 1 ? "this branch" : "these branches"} is missing from ${esc(main)}</span>
          <button type="button" class="danger" data-gitdeletemerged="${esc(clearable.map(b => b.name).join(" "))}"
            title="delete every branch already in ${esc(main)}">Delete ${clearable.length === 1 ? "it" : `all ${clearable.length}`}</button>
        </div>`) : "")
      + (remoteOnly.length ? `<details class="sect gremote" data-sect="git:remote"${sectOpen["git:remote"] ? " open" : ""}><summary><span class="t">only on ${esc(host)}</span>
          <span class="sst">${remoteOnly.length}</span></summary><div class="body">${remoteOnly.map(branchRow).join("")}</div></details>` : "");
    // Conflicts stop everything else, so they are said first, with the one
    // button that helps: the merge in progress handed to the session.
    const conflicts = files.filter(f => f.state === "conflict");
    const conflictBar = conflicts.length && !locked ? `<div class="actbar gconflict">
        <span class="state bad">${conflicts.length} file${conflicts.length === 1 ? "" : "s"} in conflict: the merge is not finished</span>
        <button type="button" class="primary" data-gitask="conflicts"
          title="hand the merge to the project's Claude session to finish">Resolve with Claude</button>
      </div>` : "";
    // What a session may do with the remote (roadmap R36): the two answers,
    // staged until Apply like every setting on the page. Enforced on the
    // relay; a local commit or merge cannot be forbidden, and the bar says so.
    const pol = {...((state?.projects || []).find(p => p.name === project)?.prefs?.gitpol || {}), ...gitPolDraft};
    const polDirty = Object.keys(gitPolDraft).length > 0;
    const policy = locked ? "" : `<div class="row stack2 gpolicy"><div class="grow">
        <div class="prefrow">
          <label class="pick">Push its branches <select data-gitpol="push">${["allow", "deny"].map(o =>
            `<option value="${o}"${(pol.push || "allow") === o ? " selected" : ""}>${o}</option>`).join("")}</select></label>
          <label class="pick">Push to ${esc(git.main || "main")} <select data-gitpol="main">${["allow", "deny"].map(o =>
            `<option value="${o}"${(pol.main || "deny") === o ? " selected" : ""}>${o}</option>`).join("")}</select></label>
        </div>
        <div class="actbar">
          <span class="state">its own branches, one at a time ${helpIcon("Applies to pushes only. Tags, deletions and remote-only branches stay yours; commits and merges here are always allowed.")}</span>
          <button type="button" id="gitPolApply"${polDirty ? "" : " disabled"}>Apply</button>
        </div></div></div>`;
    body.innerHTML = docSection("git", "changes", "Changes", files.length ? String(files.length) : "none",
        conflictBar + (files.length ? treeNote : "") + commitBar + (files.length ? fileRows : `<div class="empty">nothing changed since the last commit</div>`))
      + docSection("git", "history", "History", commits.length ? `${commits.length}${commits.length >= 100 ? "+" : ""}` : "none",
        graph + `<div id="gitDetail"${gitPick ? "" : " hidden"}></div>`)
      + docSection("git", "branches", "Branches", String(local.length), branchBar + (branchRows || `<div class="empty">no branches</div>`))
      + ciSection()
      + (policy ? docSection("git", "policy", "Claude may", `${pol.push || "allow"} · ${pol.main || "deny"}`, policy, {open: false}) : "");
    wireSections(body);
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
      if (sel.value === (saved[sel.dataset.gitpol] || (sel.dataset.gitpol === "push" ? "allow" : "deny"))) delete gitPolDraft[sel.dataset.gitpol];
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
    const nb = $("gitNewBranch");
    if (nb){
      nb.oninput = () => { gitBranchDraft = nb.value; };
      nb.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); $("gitBranchGo")?.click(); } };
    }
    const bg = $("gitBranchGo");
    if (bg) bg.onclick = async () => {
      if (!gitBranchDraft.trim()) return notify("a branch needs a name", true);
      const j = await gitAct("branch", {name: gitBranchDraft.trim(), switch: true}, gitBusy(bg), "Creating");
      if (j && j.ok) gitBranchDraft = "";
    };
    body.querySelectorAll("[data-gitdiscard]").forEach(b => b.onclick = () => {
      const path = b.dataset.gitdiscard;
      if (confirm(`Discard the changes to ${path}?\n\nIt goes back to the last commit; the change is lost.`))
        gitAct("discard", {path}, gitBusy(b), "Discarding");
    });
    body.querySelectorAll("[data-gitswitch]").forEach(b => b.onclick = () =>
      gitAct("switch", {name: b.dataset.gitswitch}, gitBusy(b), "Switching"));
    // No confirmation: a merge makes a commit rather than destroying one, and
    // the row says which way round it goes. What it can leave behind is a
    // conflict, and the Changes section is already the place that says so.
    // Another account's branch, merged in or merged into, is asked about
    // every time with the owner named; the answer rides as `confirmed`.
    body.querySelectorAll("[data-gitmerge]").forEach(b => b.onclick = () => {
      const name = b.dataset.gitmerge, into = b.dataset.gitinto || st.branch || "this branch";
      const who = b.dataset.gitwho, their = b.dataset.gitinto ? name : into;
      if (who && !confirm(`Merge ${name} into ${into}?\n\n${their} is ${who}'s session's branch.`)) return;
      gitAct("merge", {name, ...(b.dataset.gitinto ? {into: b.dataset.gitinto} : {}), ...(who ? {confirmed: true} : {})},
             gitBusy(b), "Merging");
    });
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
    body.querySelectorAll("[data-gitaskbranch]").forEach(b => b.onclick = () => {
      const row = b.closest(".gbranch"), kind = row.querySelector("[data-gitaskkind]")?.value || "merge";
      const name = b.dataset.gitaskbranch, who = b.dataset.gitwho, moves = kind === "merge" || kind === "rebase";
      if (who && moves && !confirm(`Ask Claude to ${kind} ${name} ${kind === "merge" ? "into" : "onto"} ${main}?\n\n${name} is ${who}'s session's branch.`)) return;
      gitAsk(kind, {branch: name, ...(who && moves ? {confirmed: true} : {})}, gitBusy(b));
    });
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
    body.querySelectorAll(".gcmp").forEach(d => {
      d.addEventListener("toggle", () => {
        if (d.open) gitOpenCmp.add(d.dataset.branch); else gitOpenCmp.delete(d.dataset.branch);
        if (d.open && d.querySelector(".loading")) loadGitCompare(d);
      });
      if (d.open && d.querySelector(".loading")) loadGitCompare(d);
    });
    body.querySelectorAll(".grow[data-sha]").forEach(r => r.onclick = () => {
      gitPick = gitPick === r.dataset.sha ? "" : r.dataset.sha;
      gitReveal = gitPick;
      drawGit();                 // which loads the picked commit's detail
    });
    if (gitPick) loadGitCommit(gitPick);
  }

  async function loadGitFile(d){
    const box = d.querySelector(".gdiff");
    try{
      const r = await fetch("/api/git?project=" + encodeURIComponent(project)
                            + "&what=diff&path=" + encodeURIComponent(d.dataset.path));
      const j = await r.json();
      box.innerHTML = j.error ? `<div class="hint bad">${esc(j.error)}</div>` : renderDiff(j.diff);
    }catch(e){ box.innerHTML = `<div class="hint bad">${esc(String(e))}</div>`; }
  }

  async function loadGitCompare(d){
    const box = d.querySelector(".gcmpbody");
    const main = git?.main || "main";
    try{
      const r = await fetch("/api/git?project=" + encodeURIComponent(project)
                            + "&what=compare&branch=" + encodeURIComponent(d.dataset.branch));
      const j = await r.json();
      if (j.error){ box.innerHTML = `<div class="hint bad">${esc(j.error)}</div>`; return; }
      const files = j.files || [];
      box.innerHTML = `<div class="gcmpc">${(j.commits || []).map(c => `<div class="sub"><code>${esc(c.short)}</code> ${
          esc(c.subject)} · ${esc(c.author)} · ${esc(ago(c.when))}</div>`).join("")}</div>
        <div class="sub">${files.length} file${files.length === 1 ? "" : "s"} ${esc(main)} would take: ${files.map(f =>
          `<code>${esc(f.path)}</code>${f.added != null ? ` <span class="gadd">+${f.added}</span> <span class="gdel">−${f.removed}</span>` : ""}`).join(", ")}</div>
        ${renderDiff(j.diff || "")}`;
    }catch(e){ box.innerHTML = `<div class="hint bad">${esc(String(e))}</div>`; }
  }

  async function loadGitCommit(sha){
    let box = $("gitDetail");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = `<div class="loading">loading…</div>`;
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
      box.querySelectorAll("[data-gitbranchat]").forEach(b => b.onclick = () => {
        const name = prompt(`A branch starting at ${c.short}. Its name:`);
        if (name && name.trim()) gitAct("branch", {name: name.trim(), at: b.dataset.gitbranchat, switch: true}, gitBusy(b), "Creating");
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
  const rf = $("gitRefresh");
  if (rf) rf.onclick = () => { busy(rf, "Reading"); loadGit().finally(() => { if (rf.isConnected) unbusy(rf, "Refresh"); }); };

  return {loadGit};
}
