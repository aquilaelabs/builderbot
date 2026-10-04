// The notebook's Artifacts view and the version block in its head: what the
// project built, the dev instance, the version, the changelog. One classic
// script beside index.html (docs/nodes.md §13): one file per notebook view
// (R60). A factory makeNotebook calls per notebook.

"use strict";

// A staged bump that moves the compatibility window: minor and major do,
// patch does not, and only where this project owns the window at all.
const windowMove = (part, cost) =>
  (part === "minor" || part === "major") && (cost?.projects || []).length > 0;

function nbArtifactsView({$, nb, project, root, sheet}){
  // ---- artifacts -----------------------------------------------------------
  // What this project has built. Fetched on open like Analysis, and polled
  // only while a push is live: the one time it changes on its own.
  let art = null, artTimer = null;

  async function loadArtifacts(){
    const hint = $("artHint"), list = $("artList");
    try{
      const r = await fetch("/api/artifacts?project=" + encodeURIComponent(project));
      art = await r.json();
    }catch(e){ hint.textContent = "artifacts: " + e; return; }
    if (art.error){ hint.textContent = "artifacts: " + art.error; return; }
    const rows = art.artifacts || [], job = art.push || {}, dev = art.phone;
    const groups = art.branches || [];
    // The code base itself, as a zip through the browser: a navigation, so
    // the browser's own download handles it, cookie and all.
    const src = $("artSource");
    if (src) src.onclick = () => { location.href = "/api/source?project=" + encodeURIComponent(project); };
    // Why Push and Install are ghosted, when they are: the phone is on the
    // project's node and belongs to whoever connected it there.
    const phoneWhy = !dev ? "no phone is connected on this project's node: connect one in the Phone tab, on its node"
      : !art.mine ? `connected by ${art.owner?.name || "somebody else"}: only they can push to it or install on it`
      : "";
    const inst = art.install || {};
    hint.textContent = rows.length
      ? `${rows.length} in dist/: what this project ships, newest first`
      : groups.length ? "nothing in dist/ yet; built on a branch, below" : "nothing here yet";
    {
      // Where this project compiles, as a section rather than a loose band:
      // this tab is three subjects stacked, where it builds, what it is
      // called, and what it shipped, and on a phone they arrived as one
      // scroll with nothing naming any of them. The status is the answer on
      // its own, so a shut section still says which node.
      const b = art.build || {};
      const el = $("artBuild");
      if (el){
        el.hidden = false;
        el.className = "";
        el.innerHTML = docSection("artifacts", "build", "Build",
          b.node ? (b.gap ? "agent behind" : b.name) : "no node",
          b.node && b.gap
            ? `<div class="hint bad">Nothing runs on <b>${esc(b.name)}</b> until its agent is
               updated: ${esc(b.gap)}</div>`
            : b.node
            ? `<div class="hint">Builds run on <b>${esc(b.name)}</b>${b.tools?.length
                ? `; it carries ${b.tools.map(esc).join(", ")}`
                : "; it reports no toolchains yet, so a compile will not find one"}.
               Add to it from the Tools tab.</div>`
            : `<div class="hint">No node: nothing can be compiled for this project here.
               ${esc(b.why || "")}</div>`,
          {cls: b.node ? (b.gap ? "bad" : "") : "warn"});
        wireSections(el);
      }
    }
    // Sizes as a person reads them; the bytes are nobody's unit.
    const human = n => n >= 1 << 30 ? (n / (1 << 30)).toFixed(1) + " GB"
                     : n >= 1 << 20 ? (n / (1 << 20)).toFixed(1) + " MB"
                     : n >= 1 << 10 ? Math.round(n / (1 << 10)) + " KB"
                     : n + " B";
    // The dev instance: a service in the file list's row language. Not a
    // file (nothing in dist/ backs it), but the operator asked for it where
    // the push and download buttons live, and a row with state and actions
    // is exactly what this list already speaks.
    const da = art.devapp || {};
    // Every container of the project's own, one row each, the first
    // carrying the ids the rest of this view and the suite address. The
    // row described the project's own instance whether or not it existed,
    // so a project whose only container was web-dev read "web (down)" with
    // web-dev nowhere on the tab (B300). A project with no container yet
    // keeps its one row, which is what Send is for.
    const insts = (art.devapps || []).filter(d => d && d.compose
      && (d.exists || d.running || d.built_rev || d.job?.running || d.job?.error));
    const shown = insts.length ? insts : da.compose ? [da] : [];
    const daJob = shown.find(d => d.job?.running)?.job || da.job;
    const devTcpOf = d => (d.ports || []).filter(p => p.proto === "TCP" && p.published);
    const devUrl = p => `http://${daemonHost()}:${p.published}/`;
    const devLines = (label, items, cls) => !items?.length ? "" :
      `<div class="dim ${cls}">${label}</div>`
      + items.map(x => `<div class="dim ${cls} li">${esc(x)}</div>`).join("");
    const rowFor = (da, i) => {
    const daJob = da.job;
    // The same row the files use, because it IS one of the rows: kind on a
    // pill, the thing's own name in bold, what is known about it underneath.
    // The pill says what it is (docker) rather than what it is doing; the
    // doing goes in parentheses after the name, where an artifact's size and
    // age go. A list whose rows are shaped alike is read; one where every row
    // argues its own case is scanned.
    const devState = da.running ? "running" : da.exists ? "stopped" : "down";
    // The ports and the mounts, written the way Unraid's own Docker tab writes
    // them, because that is where the operator reads the same two facts about
    // every other container on the box, and a second notation for them would
    // be one to translate every time. Container side on the left, host side on
    // the right, and the arrow says which way it goes: one way in for a
    // read-only mount and for a published port, both ways for a writable one.
    //
    // The host is this page's own address, which is the honest answer to
    // "where do I reach that port": the dashboard and the published port are
    // on the same machine, and this is the name the operator got there by.
    // A way in. One published port is a link straight there; several is a
    // question, and the answer is the operator's; nothing here knows which
    // of them is the web UI, and Unraid does not either: its own tab reads a
    // port somebody wrote into a template, or the net.unraid.docker.webui
    // label. So the single case is known, and the rest is asked rather than
    // guessed. Only while it is up: a link to a port with nothing behind it
    // is a broken link.
    const devTcp = devTcpOf(da);
    // The route's URL when the instance has one (docs/nodes.md §7): a
    // funnel's public address, or lan on the node the instance is on: else
    // the old guess from the daemon's host.
    const devWeb = !da.running ? ""
      : da.route?.url && da.route.ready ? da.route.url
      : devTcp.length === 1 ? devUrl(devTcp[0]) : "";
    const devAsk = da.running && devTcp.length > 1;
    // The ports and mounts used to be listed here, unfolded, on the reasoning
    // that they are what the instance IS. They are, and this is no longer the
    // screen that runs it. Building, bringing up and taking down all moved to
    // the Docker manager, where every container of every project lives; a
    // second copy of a container's wiring on the tab you send it FROM is a
    // thing to keep in step for no reader. The manager's rows fold it open.
    // One line each, never a run-on joined by semicolons. These are separate
    // facts about separate services and reading them is the whole point.
    return `
      <div class="artrow${i ? " devRow" : ""}"${i ? ` data-devrow="${i}"` : ' id="devRow"'}>
        <div class="grow">
          <div class="top"><span class="pill">docker</span>
            <b>${esc(da.name || "dev instance")}</b>
            <span class="dim state ${da.running ? "ok" : ""}">(${devState})</span></div>
          <div class="dim">${
            daJob?.running ? esc(daJob.step || "working") + '<span class="dots"></span>'
            // The reason's head and its last words, on one line: "build
            // failed: stub build exploded". The whole output is the Jobs
            // tab's, and the shell's through the Tests view.
            : daJob?.error ? esc((l => l.length > 1 && l[0] !== l[l.length - 1] ? `${l[0]} ${l[l.length - 1]}` : l[0] || "")(
                String(daJob.error).split("\n").map(x => x.trim()).filter(Boolean)))
            : da.await_env ? "built: fill in the env (Env), then Up"
            : da.interrupted ? `a build was interrupted: BuilderBot restarted
                while it was running${da.built_rev
                  ? `; still on ${esc(da.built_rev)}` : ", and nothing was built"}`
            : da.built_rev ? `built from ${esc(da.built_rev)}${
                da.changed_why === "moved" ? ": the code has moved since"
                : da.changed_why === "dirty"
                  ? ": uncommitted changes are not in it" : ""}`
            // Nothing, where it used to say "never built: Build makes the
            // first image". That sentence named a button this screen no longer
            // has: building moved to the Docker manager with the rest of the
            // running controls, and an instruction pointing at a control that
            // is not here is worse than silence. The states that remain are
            // facts about THIS project's build, which is what this tab is for.
            : ""}</div>
          ${devLines("will not work as written", da.problems, "bad")}
          ${devLines("asks for more than its own directory", da.risks, "risk")}${
          // A port another container holds is not a fault in the file: the
          // instance Send makes gets an env of its own, and the port goes in
          // it. So a note, in the quiet voice, not a verdict in red.
          da.port_clash?.length ? `<div class="dim li">port ${esc(da.port_clash.join(", "))} ${
            da.port_clash.length === 1 ? "is" : "are"} already published on this node</div>` : ""}
        </div>
        <span class="acts">
          ${devWeb ? `<a class="btn" href="${esc(devWeb)}" target="_blank"
            rel="noreferrer" title="open ${esc(devWeb)}">Open</a>` : ""}
          ${devAsk ? `<button type="button" data-devopen="${i}"${i ? "" : ' id="devOpen"'}
            title="it publishes ${devTcp.length} ports: pick one">Open</button>` : ""}
          ${i ? "" : `<button type="button" id="devSend" class="primary"
            title="make a container from this project and manage it on the Docker tab"
            >Send to Docker manager</button>`}
        </span>
      </div>`;
    };
    const devHtml = !da.compose ? "" : !da.available ? `
      <div class="artrow job"><span class="pill">docker</span>
        <span class="grow">${esc(da.why || "docker is not reachable")}${
          // The machine it asked, because an instance stays on the node it
          // was made on: "it could not find the daemon on the node I pointed
          // it at" is the same sentence whether it looked there or somewhere
          // else, and only this tells the two apart.
          da.daemon || da.where ? ` <span class="dim">(${esc(da.daemon || da.where)})</span>` : ""}</span>
      </div>` : shown.map(rowFor).join("");
    // An install is one shot rather than a session, so it reports its own
    // line: what it is doing, and what went wrong in words when it does.
    // The push session, as a row: live once web-ext says the add-on is on
    // the phone, with Stop, which is how the session ends.
    const jobHtml = job.running || (job.state === "stopped" && job.error) ? `
      <div class="artrow job">
        <span class="pill ${job.state === "running" ? "ok" : job.error ? "bad" : "go"}">${
          job.state === "running" ? "live" : job.error ? "stopped" : "starting"}${
          job.running && job.state !== "running" ? `<span class="dots"></span>` : ""}</span>
        <span class="grow">${esc(job.what)}${job.error ? `: ${esc(job.error)}`
          : `: temporary, gone when Firefox restarts; changes do <b>not</b>
          push themselves, so rebuild the .xpi and push again.`}</span>
        ${job.running ? `<button type="button" id="artStop">Stop</button>` : ""}
      </div>` : "";
    const instHtml = inst.running || inst.state === "failed" ? `
      <div class="artrow job">
        <span class="pill ${inst.state === "failed" ? "bad" : "go"}">${
          inst.state === "failed" ? "failed" : "installing"}${
          inst.running ? `<span class="dots"></span>` : ""}</span>
        <span class="grow">${esc(inst.what)}${
          inst.error ? `: ${esc(inst.error)}` : ""}</span>
      </div>` : "";
    // Dev builds go on their own past the newest few of each (R105): said
    // once, over the list, where there are any.
    const keep = art.dev_keep ?? 3;
    const devNote = rows.some(a => /\d+\.\d+\.\d+-dev\.\d+-[0-9a-f]{7}/.test(a.name))
      ? `<div class="hint dim">${keep
          ? `Dev builds keep the newest ${keep} of each (the project's settings say how many); older ones are removed as new ones arrive. A release is kept, and so is anything pinned.`
          : "Every dev build is kept: this project's settings say so (Dev builds kept)."}</div>` : "";
    list.innerHTML = devHtml + (!rows.length
      ? `<div class="hint">Nothing in <b>dist/</b> yet: a build copies what it keeps there.</div>`
      : devNote + jobHtml + instHtml + rows.map((a, i) => `
        <div class="artrow">
          <span class="grow">
            <span class="top"><span class="pill">${esc(a.kind)}</span>
              <b>${esc(a.name)}</b>${a.pinned ? ` <span class="pill on">pinned</span>` : ""}${
              a.prov?.signed ? ` <span class="pill ok">signed</span>` : ""}</span>
            <span class="dim">${esc(human(a.size))} · ${esc(ago(a.at))}${
              a.path !== a.name ? ` · ${esc(a.path)}` : ""}${
              a.pinned && a.pinned_by ? ` · pinned by ${esc(a.pinned_by)}` : ""}</span>${
            // What built it, when a job did (docs/nodes.md §6): the job,
            // the node, the snapshot. A file somebody copied in says nothing.
            a.prov ? `<span class="dim">built by ${esc(a.prov.job)} on ${
              esc((nodesList || []).find(n => n.id === a.prov.node)?.name || a.prov.node || "?")}${
              a.prov.source?.digest ? ` from snapshot ${esc(a.prov.source.digest.slice(7, 19))}` : ""}${
              a.prov.sha256 ? ` · sha256 ${esc(a.prov.sha256.slice(0, 12))}` : ""}</span>` : ""}${
            // What signed it (R106 step 4): the key, what verified, and the
            // certificate's whole fingerprint, which a store's metadata asks
            // for (F-Droid's AllowedAPKSigningKeys) and a person compares.
            a.prov?.signed ? `<span class="dim">signed with the ${
              a.prov.signed.key && a.prov.signed.key !== "default" ? `${esc(a.prov.signed.key)} key's ` : ""}${
              a.prov.signed.route === "play" ? "Play upload key" : "sideload signing key"}${
              a.prov.signed.from ? ` from ${esc(a.prov.signed.from)}` : ""}${
              a.prov.signed.schemes?.length ? `, verified ${esc(a.prov.signed.schemes.join(", "))}` : ""}${
              a.prov.signed.rotated_from ? `, rotated from ${esc(a.prov.signed.rotated_from)}: Android 8.1 and older still see ${esc(a.prov.signed.rotated_from)}` : ""}</span>
              <span class="artfp">SHA-256 ${esc(a.prov.signed.cert.match(/../g).join(":"))}
                <button type="button" class="link" data-artfp="${i}" title="the fingerprint as F-Droid's AllowedAPKSigningKeys takes it: lowercase, no colons">Copy for F-Droid</button></span>` : ""}</span>
          <span class="acts">
            ${a.kind === "apk" ? `<button type="button" data-artinstall="${i}"${
                inst.running || phoneWhy ? " disabled" : ""} title="${
                phoneWhy ? esc(phoneWhy)
                : inst.running ? "one install at a time"
                : "install it on the phone, replacing any copy already there"
                }">Install</button>` : ""}
            ${a.kind === "xpi" ? `<button type="button" data-artpush="${i}"${
                job.running || phoneWhy || !art.webext ? " disabled" : ""} title="${
                phoneWhy ? esc(phoneWhy)
                : !art.webext ? `web-ext is not on ${esc(art.node_name || "the node")}: install it there first`
                : job.running ? "one push at a time"
                : "install it on the phone, temporarily"}">Push</button>` : ""}
            ${(a.kind === "apk" || a.kind === "aab") && !/-signed\.(apk|aab)$/.test(a.name)
              ? (art.sign_routes || []).map(r => `<button type="button" data-artsign="${i}" data-route="${r}"
                title="sign it on the project's node with its ${r === "play" ? "Play upload key" : "sideload signing key"}; it arrives beside it as -signed">Sign${
                  (art.sign_routes || []).length > 1 ? (r === "play" ? " for Play" : " to sideload") : ""}</button>`).join("") : ""}
            ${a.view ? `<button type="button" data-artview="${i}"
                title="read it here, without downloading it">View</button>` : ""}
            <a class="btn" href="/api/artifact?project=${encodeURIComponent(project)
              }&path=${encodeURIComponent(a.path)}" download>Download</a>
            <button type="button" class="eye pin${a.pinned ? " on" : ""}" data-artpin="${i}"
              aria-label="${a.pinned ? "unpin" : "pin"}" title="${a.pinned
                ? "unpin: it goes like any other build when newer ones arrive"
                : "pin: keep it, whatever builds come after it"}">${TACK}</button>
          </span>
        </div>`).join(""));
    paginate(list, ":scope > .artrow", {key: "artList", noun: "files"});
    // What a session looked with (R96): a reel's sheet, an emulator shot.
    // One fold apart from the files, since they are not what ships, each
    // row saying whose it is and when. They go by age (the project's
    // "captures kept" days, swept by the server on this read) or by Remove
    // here: never by need, because nothing can tell whether another
    // session is still reading one. Hidden when there are none: nothing to
    // act on.
    const capBox = $("artCaptures");
    const caps = art.captures || [];
    if (capBox){
      capBox.hidden = !caps.length;
      const days = art.capture_days ?? 7;
      capBox.innerHTML = !caps.length ? "" : docSection("artifacts", "captures", "Captures",
        `${caps.length}, kept ${days ? `${days} day${days === 1 ? "" : "s"}` : "until removed"}`,
        `<div class="hint">What a session looked with: a reel's sheet (<b>bb capture reel</b>) or an
           emulator shot, not what the project ships. ${days
             ? `Each is removed ${days} day${days === 1 ? "" : "s"} after it was taken`
             : "Kept until somebody removes one"}; the project's settings say how long.</div>`
        + caps.map((c, i) => `
        <div class="artrow">
          <span class="grow">
            <span class="top"><span class="pill">${esc(c.kind)}</span> <b>${esc(c.name)}</b></span>
            <span class="dim">${esc(c.by ? `by ${c.by}` : "by nobody known")} · ${esc(ago(c.at))} · ${esc(human(c.size))}${
              c.kind === "reel" ? ` · ${c.frames} frame${c.frames === 1 ? "" : "s"}` : ""}</span></span>
          <span class="acts">
            <a class="btn" href="/api/artifact?project=${encodeURIComponent(project)
              }&path=${encodeURIComponent(c.path)}" download>Download</a>
            <button type="button" data-artcap="${i}" title="remove it from dist/ now, for everybody">Remove</button>
          </span>
        </div>`).join(""), {open: false});
      wireSections(capBox);
      capBox.querySelectorAll("[data-artcap]").forEach(b => b.onclick = async () => {
        const c = caps[+b.dataset.artcap];
        if (!c) return;
        busy(b, "Removing");
        try{
          const j = await (await postJSON("/api/artifacts", {project, action: "forget-capture", name: c.name})).json();
          if (j.error) return notify(j.error, true);
        }catch(e){ return notify(String(e), true); }
        loadArtifacts();
      });
    }
    // Builds made on a branch, in each account's worktree (B237): Download
    // and View, carrying the tree. Install and Push stay with dist/, whose
    // files the phone's node is sent by their path in the project.
    const brList = $("artBranches");
    const brRows = groups.flatMap(g => g.artifacts.map(a => ({...a, tree: g.uid})));
    if (brList){
      brList.hidden = !brRows.length;
      let at = 0;
      brList.innerHTML = !brRows.length ? "" : `<div class="hint">Built on a branch. Merge it to main to put its build in dist/.</div>`
        + groups.map(g => `<div class="sub dim ggroup">${esc(g.who === state?.me ? "your" : `${g.who}'s`)} branch builds${
            g.branch ? `, on ${esc(g.branch)}` : ""}</div>` + g.artifacts.map(a => { const i = at++; return `
          <div class="artrow">
            <span class="grow">
              <span class="top"><span class="pill">${esc(a.kind)}</span> <b>${esc(a.name)}</b></span>
              <span class="dim">${esc(human(a.size))} · ${esc(ago(a.at))}</span></span>
            <span class="acts">
              ${a.view ? `<button type="button" data-artbview="${i}"
                  title="read it here, without downloading it">View</button>` : ""}
              <a class="btn" href="/api/artifact?project=${encodeURIComponent(project)
                }&path=${encodeURIComponent(a.path)}&tree=${encodeURIComponent(g.uid)}" download>Download</a>
            </span>
          </div>`; }).join("")).join("");
      paginate(brList, ":scope > .artrow", {key: "artBranches", noun: "files"});
      brList.querySelectorAll("[data-artbview]").forEach(b => b.onclick = async () => {
        const a = brRows[Number(b.dataset.artbview)];
        const pane = document.createElement("div");
        pane.className = "verlogpane";
        nb.openSheet(a.name, [pane]);
        pane.innerHTML = `<div class="loading">loading…</div>`;
        try{
          const r = await fetch(`/api/artifact?project=${encodeURIComponent(project)
                                }&path=${encodeURIComponent(a.path)}&tree=${encodeURIComponent(a.tree)}`);
          pane.textContent = r.ok ? await r.text() : `could not read ${a.name}`;
        }catch(e){ pane.textContent = String(e); }
      });
    }
    if (!tcDotsTimer && list.querySelector(".dots"))
      tcDotsTimer = setInterval(tcTickDots, 400);
    list.querySelectorAll("[data-devopen]").forEach(b => b.onclick = () => {
      const devTcp = devTcpOf(shown[Number(b.dataset.devopen)] || {});
      const box = document.createElement("div");
      box.className = "portpick";
      box.innerHTML = `<div class="hint">It publishes ${devTcp.length} ports: pick one.</div>`
        + devTcp.map(p => `<a class="btn" href="${esc(devUrl(p))}" target="_blank"
            rel="noreferrer">${esc(daemonHost())}:${esc(p.published)}
            <span class="dim">→ ${esc(p.target)}:${esc(p.proto)}</span></a>`).join("");
      box.querySelectorAll("a").forEach(a => a.addEventListener("click", nb.closeSheet));
      nb.openSheet("Open which port?", [box]);
    });
    const send = list.querySelector("#devSend");
    if (send) send.onclick = () => openSendToDocker(project, art.send_as, (art.devapps || []).length);
    // THIS project's daemon, which is its node's and need not be the default
    // one the poll asked about. The row above already draws the reason when
    // there is one, so what is passed here is the same answer the row is
    // wearing rather than a second opinion about another machine.
    gateDocker(list, !da.compose ? "" : da.available ? ""
                     : (da.why || "docker is not reachable"));
    list.querySelectorAll("[data-artpush]").forEach(b => b.onclick = async () => {
      const a = rows[Number(b.dataset.artpush)];
      busy(b, "Pushing");
      await postArtifacts({action: "push", path: a.path,
                           apk: (art.apks || [])[0] || ""});
    });
    list.querySelectorAll("[data-artinstall]").forEach(b => b.onclick = async () => {
      const a = rows[Number(b.dataset.artinstall)];
      busy(b, "Installing");
      await postArtifacts({action: "install", path: a.path});
    });
    // A shipped script is a thing people read before they run it, and on a
    // phone a download is the end of that. Over the panel like a History, the
    // text as it is; nothing here runs it, and the tab has no way to.
    // Sign (R106): a job on the project's node with the project's key,
    // which never comes near the page either; the signed build arrives in
    // dist/ beside this one, and the list picks it up when it lands.
    list.querySelectorAll("[data-artsign]").forEach(b => b.onclick = async () => {
      const a = rows[+b.dataset.artsign];
      if (!a) return;
      b.disabled = true;
      const j = await (await postJSON("/api/signing", {action: "sign", project, file: a.path,
                                                       route: b.dataset.route})).json().catch(() => ({}));
      if (j.error){ b.disabled = false; return notify(j.error, true); }
      notify(`signing ${a.name} on the node: it arrives here as ${a.name.replace(/(-unsigned)?\.(apk|aab)$/, "-signed.$2")}`);
    });
    list.querySelectorAll("[data-artfp]").forEach(b => b.onclick = async () => {
      const a = rows[+b.dataset.artfp];
      const fp = String(a?.prov?.signed?.cert || "").toLowerCase();
      try{ await navigator.clipboard.writeText(fp); notify(`copied ${a.name}'s signing fingerprint`); }
      catch(e){ notify(`copy it by hand: ${fp}`, "warn"); }
    });
    list.querySelectorAll("[data-artpin]").forEach(b => b.onclick = async () => {
      const a = rows[+b.dataset.artpin];
      if (!a) return;
      b.disabled = true;
      try{
        const j = await (await postJSON("/api/artifacts", {project, action: a.pinned ? "unpin" : "pin", path: a.path})).json();
        if (j.error){ b.disabled = false; return notify(j.error, true); }
        notify(j.pinned ? `pinned ${a.name}: it stays` : `unpinned ${a.name}`);
      }catch(e){ b.disabled = false; return notify(String(e), true); }
      loadArtifacts();
    });
    list.querySelectorAll("[data-artview]").forEach(b => b.onclick = async () => {
      const a = rows[Number(b.dataset.artview)];
      const pane = document.createElement("div");
      pane.className = "verlogpane";
      nb.openSheet(a.name, [pane]);
      pane.innerHTML = `<div class="loading">loading…</div>`;
      try{
        const r = await fetch(`/api/artifact?project=${encodeURIComponent(project)
                              }&path=${encodeURIComponent(a.path)}`);
        pane.textContent = r.ok ? await r.text() : `could not read ${a.name}`;
      }catch(e){ pane.textContent = String(e); }
    });
    const stop = $("artStop");
    if (stop) stop.onclick = () => postArtifacts({action: "stop"});
    clearInterval(artTimer); artTimer = null;
    // Polled while either thing is in flight. An install is the slower of the
    // two (a 24MB APK over wifi) and is the reason this exists at all.
    if ((job.running || inst.running || daJob?.running)
        && !root.querySelector('[data-view="artifacts"]').hidden)
      artTimer = setTimeout(loadArtifacts, 2000);
  }

  // ---- the version, in the head of the tab whose files carry it ----------
  // Two jobs, and they are not the same job. The display answers "what is
  // this at", which needs no decision and is on all the time. The buttons
  // answer "what should it be next", which is rare, and is hard here for a
  // specific reason the operator named: most of the coding happens through
  // prompts, so by bump time nobody remembers what the last three weeks
  // contained. Hence the evidence line; that is the half that makes the
  // decision two seconds instead of a scroll through git log.
  let ver = null;
  // A bump is staged, not written. Pressing Patch/Minor/Major only records
  // the intent: Save commits it, Revert and leaving the tab throw it away.
  // Everything else in this notebook works that way, and a bump is the one
  // control here that reaches outside the panel: a misclicked "Major → 1.0.0"
  // used to be a commit before the finger left the button.
  // {component -> part}, "" being the project's own.
  let verPending = {};
  let verPolicyPending = null;   // a picked policy, until Save writes it

  async function loadVersion(){
    const box = $("verBox");
    try{
      const r = await fetch("/api/version?project=" + encodeURIComponent(project));
      ver = await r.json();
    }catch(e){ box.textContent = "version: " + e; return; }
    if (ver.error && !ver.target){
      // A malformed VERSION is worth saying out loud: everything downstream
      // assumes the shape, so this is the one place it can be reported, in
      // the section the number itself lives in, or it would be the one band
      // on this tab with nothing naming it. "unavailable" rather than a
      // guess at which, because this branch is both a malformed VERSION and
      // a project with no git behind it; the body says which.
      box.innerHTML = docSection("artifacts", "version", "Version", "unavailable",
        `<div class="verln"><span>version</span><code>${esc(ver.error)}</code></div>`,
        {cls: "warn"});
      wireSections(box);
      return;
    }
    drawVersion();
  }

  // A repo can ship two products, and then one number is a lie: an extension
  // at 2.1 beside an app at 0.3 do not share a maturity. So the block is one
  // section per VERSION file the project carries: almost always just the
  // one, because a component exists only where somebody put a file.
  function drawVersion(){
    const box = $("verBox");
    const all = [ver, ...(ver.versions || [])];
    // One section per VERSION file, which is almost always one, and the
    // number is its status, so a shut section still answers the question the
    // tab is opened with. They used to be bands separated by a rule, with a
    // wall of bump buttons under each and nothing naming either.
    box.innerHTML = all.map(v => docSection("artifacts",
      `version${v.component ? ":" + v.component : ""}`,
      all.length > 1 ? (v.component || `${v.project} (the project)`) : "Version",
      v.target || "no VERSION file",
      verSection(v),
      {cls: v.target ? "" : "warn"})).join("");
    wireSections(box);
    // Releasing: outward-facing, and the one thing on this tab other people
    // fetch. Confirmed by name, because a pushed tag is not taken back from
    // here, or anywhere, without thinking about who has it.
    box.querySelectorAll("[data-verrelease]").forEach(b => b.onclick = async () => {
      const comp = b.dataset.verrelease || "";
      const blk = all.find(x => (x.component || "") === comp);
      const tag = comp ? `${comp}-v${blk?.target}` : `v${blk?.target}`;
      if (!confirm(`Release ${blk?.target}?\n\n`
                   + `Tags this commit as ${tag} and pushes the tag; a pushed tag is not moved or deleted from here.`)) return;
      busy(b, "Releasing");
      box.querySelectorAll("button,select").forEach(x => x.disabled = true);
      const j = await postVersion({action: "release", component: comp});
      if (j?.released?.tag)
        notify(j.released.note
               || `${j.released.tag} tagged and pushed`);
    });
    box.querySelectorAll("[data-verunbump]").forEach(b => b.onclick = async () => {
      const comp = b.dataset.verunbump || "";
      const blk = all.find(x => (x.component || "") === comp);
      if (!confirm(`Take ${comp ? comp + "'s" : "this project's"} version back `
                   + `from ${blk?.target} to ${blk?.prev}?\n\n`
                   + `The code stays; ${blk?.target}'s changelog lines return to Unreleased.`)) return;
      box.querySelectorAll("button,select").forEach(x => x.disabled = true);
      await postVersion({action: "unbump", component: comp});
    });
    // Published to the panel-level Save/Revert, which live outside this
    // closure. Rebound on every draw so they always close over this
    // notebook's own state rather than whichever one drew last.
    nb.verStagedCount = () => Object.keys(verPending).length + (verPolicyPending != null ? 1 : 0);
    nb.verClearStaged = () => { verPending = {}; verPolicyPending = null; drawVersion(); };
    nb.verCommitStaged = async () => {
      const parts = Object.entries(verPending);
      const policy = verPolicyPending;
      if (!parts.length && policy == null) return "";
      // A window move is the one thing on this tab that reaches other
      // projects: it ends their sessions. Asked here as well as said on the
      // staged line, because the line can be scrolled past and this cannot
      // (B92). Anything else saves without a question, as it always has.
      const cost = ver?.window_cost;
      const moves = parts.find(([comp, part]) => !comp && windowMove(part, cost));
      if (moves && !confirm(
            `Bump the ${moves[1]}? This moves the compatibility window.\n\n`
            + `Sessions on ${cost.projects.length} project${cost.projects.length === 1 ? "" : "s"} `
            + `(${cost.projects.join(", ")}) end until each node's agent is updated on the Nodes tab.`)) return "";
      verPending = {}; verPolicyPending = null;
      const done = [];
      if (policy != null){
        const j = await postVersion({action: "policy", policy}, true);
        if (j && !j.error) done.push(`Claude access: ${POLICY_LABEL[policy] || policy}`);
      }
      for (const [comp, part] of parts){
        const j = await postVersion({action: "bump", part, component: comp},
                                    true);
        if (j?.bumped) done.push(`${comp || "version"} ${j.bumped.was} → ${j.bumped.target}`);
      }
      return done.join(" · ");
    };
    // ---- the changelog, as something you can shape ------------------------
    // It used to be the file as text, which is right for reading and useless
    // for the thing it is actually for: a cycle's entries are written by
    // sessions, one at a time, in the order the work happened, and what a
    // person reads at a release wants an arrangement. Categories, their
    // order, the order inside them, the words: all of it here.
    //
    // Unreleased only. Everything below it is a release somebody may have
    // read, shown as the text it is; `bb version unroll` is how one is
    // reopened, which is a gesture that says what it is.
    function drawChangelog(pane, comp, j){
      let gs = JSON.parse(JSON.stringify(j.groups || []));
      const dated = (j.text || "").split(/\n(?=## (?!Unreleased))/s).slice(1).join("\n");
      const names = () => [...new Set(gs.map(g => g.name))];
      const flat = () => gs.flatMap(g => g.entries.map(e => [g, e]));
      const swap = (a, i, k) => { const t = a[i]; a[i] = a[i + k]; a[i + k] = t; };

      // Where the reader was, across a redraw. Every gesture here rebuilds the
      // whole pane, which is fine for ten entries and not for sixty, where
      // one press of ↑ threw away the scroll position and the focus, so
      // moving a line three places meant finding its button three times.
      // `keep` is the ENTRY OBJECT rather than an index, because the indices
      // are what the move just changed.
      // The sheet's slot is what scrolls (`.box.sheet .sheetslot{overflow:auto}`),
      // and the pane is its child. Named rather than walked, because a guess
      // that finds the wrong element restores a scroll nobody moved.
      const scroller = () => pane.closest(".sheetslot") || pane.parentElement;
      const draw = (keep, sel) => {
        const opts = (cur) => ["", ...names().filter(Boolean)]
          .map(n => `<option value="${esc(n)}"${n === cur ? " selected" : ""}>${
            esc(n || "no category")}</option>`).join("")
          + `<option value="\u0000new">new category…</option>`;
        const box = scroller();
        const top = box ? box.scrollTop : null;
        pane.innerHTML =
          `<div class="clog">
             <div class="hint">Sessions add the lines; the order and the words are yours. Save writes CHANGELOG.md.</div>
             ${gs.length ? gs.map((g, gi) => `
               <div class="clgroup" data-g="${gi}">
                 ${g.name ? `<div class="clhead">
                   <input class="clname" value="${esc(g.name)}" maxlength="40"
                          aria-label="category name">
                   <button type="button" data-cmv="up" data-g="${gi}"
                     ${gi === 0 ? "disabled" : ""} title="move this category up">↑</button>
                   <button type="button" data-cmv="down" data-g="${gi}"
                     ${gi === gs.length - 1 ? "disabled" : ""} title="move this category down">↓</button>
                 </div>` : ""}
                 ${g.entries.map((e, ei) => `
                   <div class="clrow" data-g="${gi}" data-e="${ei}">
                     <textarea class="cltext proseline" rows="1" maxlength="300"
                       aria-label="what changed">${esc(e.text)}</textarea>
                     <div class="clmeta" title="${esc((e.shas || []).join(", "))}">
                       <select class="clcat" aria-label="category">${opts(g.name)}</select>
                       <span class="clsha">${esc((e.shas || []).join(", ")) || "none"}</span>
                       <span class="sp"></span>
                       <button type="button" data-emv="up" title="move up">↑</button>
                       <button type="button" data-emv="down" title="move down">↓</button>
                       <button type="button" class="danger" data-erm
                         title="drop this line: the commit is untouched">✕</button>
                     </div>
                   </div>`).join("")}
               </div>`).join("")
             : `<div class="empty">nothing unreleased here yet</div>`}
             <div class="actbar"><span class="state" id="clState"></span>
               <button type="button" class="primary" id="clSave">Save</button></div>
           </div>
           ${dated ? `<div class="verlogpane">${esc(dated)}</div>` : ""}`;
        wire();
        if (top != null && box) box.scrollTop = top;
        if (keep){
          const at = flat().findIndex(([, x]) => x === keep);
          const row = at >= 0 ? pane.querySelectorAll(".clrow")[at] : null;
          row?.querySelector(sel || "textarea")?.focus();
        }
      };

      const wire = () => {
        const q = (sel, fn) => pane.querySelectorAll(sel).forEach(fn);
        q("[data-cmv]", b => b.onclick = () => {
          const gi = Number(b.dataset.g);
          swap(gs, gi, b.dataset.cmv === "up" ? -1 : 1);
          draw();
        });
        q(".clname", i => i.onchange = () => {
          gs[Number(i.closest(".clgroup").dataset.g)].name = i.value.trim();
          draw();
        });
        q(".clrow", row => {
          const g = gs[Number(row.dataset.g)], e = g.entries[Number(row.dataset.e)];
          // The growing is proseline()'s, wired by the observer when the row
          // appears; this only has to hear the words change.
          row.querySelector(".cltext").onchange = ev => { e.text = ev.target.value; };
          row.querySelector("[data-erm]").onclick = () => {
            g.entries.splice(g.entries.indexOf(e), 1);
            gs = gs.filter(x => x.entries.length);
            draw();
          };
          row.querySelectorAll("[data-emv]").forEach(b => b.onclick = () => {
            // Across the whole section, not within the group: a line moved
            // off the end of one category lands in the next, which is what
            // "move it down" looks like to somebody dragging a list.
            const all = flat();
            const at = all.findIndex(([, x]) => x === e);
            const to = at + (b.dataset.emv === "up" ? -1 : 1);
            if (to < 0 || to >= all.length) return;
            const [tg] = all[to];
            g.entries.splice(g.entries.indexOf(e), 1);
            if (tg === g) g.entries.splice(g.entries.indexOf(all[to][1])
                                           + (b.dataset.emv === "up" ? 0 : 1), 0, e);
            else tg.entries.splice(b.dataset.emv === "up" ? tg.entries.length : 0, 0, e);
            gs = gs.filter(x => x.entries.length);
            // ...and the button that moved it is under the same finger, so a
            // line goes three places in three presses rather than three hunts.
            draw(e, `[data-emv="${b.dataset.emv}"]`);
          });
          row.querySelector(".clcat").onchange = ev => {
            let to = ev.target.value;
            if (to === "\u0000new"){
              to = (prompt("Name the new category") || "").trim();
              if (!to){ draw(); return; }
            }
            g.entries.splice(g.entries.indexOf(e), 1);
            let hit = gs.find(x => x.name === to);
            if (!hit){ hit = {name: to, entries: []}; gs.push(hit); }
            hit.entries.push(e);
            gs = gs.filter(x => x.entries.length);
            draw();
          };
        });
        const save = pane.querySelector("#clSave");
        if (save) save.onclick = async () => {
          busy(save, "Saving");
          try{
            const r = await postJSON("/api/changelog", {project, component: comp, groups: gs});
            const a = await r.json();
            if (a.error){ notify(a.error, true); return; }
            gs = a.groups || [];
            pane.querySelector("#clState").textContent =
              `saved: ${a.entries} line${a.entries === 1 ? "" : "s"}`;
            loadVersion();
          }catch(e){ notify("changelog: " + e, true); }
          finally{ if (save.isConnected) unbusy(save, "Save"); }
        };
      };
      draw();
    }

    box.querySelectorAll("[data-verlog]").forEach(b => b.onclick = async () => {
      const comp = b.dataset.verlog || "";
      if (b.classList.contains("on")){ nb.closeSheet(); return; }
      // Built for the sheet rather than rendered into the box and moved there.
      // It used to live in #verBox, hidden, and nb.openSheet() moved it, so a
      // repaint of the box while the sheet was open (a version poll, a dist
      // change) put a second, empty .verlogpane back in the box, and anything
      // looking for "the changelog pane" found whichever came first in the
      // document. nb.openSheet takes a parentless element and drops it on close,
      // so there is now exactly one at a time, or none.
      const pane = document.createElement("div");
      pane.className = "verlogpane";
      pane.dataset.verlogpane = comp;
      // A changelog is prose someone wrote to be read, and it was opening as a
      // block wedged between the version's own controls. Over the panel, like
      // the four histories, with room for the lines it is made of.
      b.classList.add("on");
      nb.openSheet(`Changelog${comp ? ": " + comp : ""}`, [pane],
                () => b.classList.remove("on"));
      pane.innerHTML = `<div class="loading">loading…</div>`;
      try{
        const r = await fetch(`/api/changelog?project=${encodeURIComponent(project)}`
                              + `&component=${encodeURIComponent(comp)}`);
        const j = await r.json();
        if (j.error){ pane.textContent = `changelog: ${j.error}`; return; }
        if (j.text == null){
          // No file yet. The first line can be written here as well as by
          // a session's `bb changelog add`: the editor used to sit dead
          // until Claude made the file.
          pane.innerHTML = `<div class="sub">no CHANGELOG.md yet: write the first line, or a session's first entry creates it</div>
            <div class="actbar"><input id="clFirst" maxlength="300" autocomplete="off"
              placeholder="what changed for the person using it, in their words">
              <button type="button" class="primary" id="clFirstGo">Create</button></div>`;
          pane.querySelector("#clFirstGo").onclick = async () => {
            const text = pane.querySelector("#clFirst").value.trim();
            if (!text) return notify("write the line first", true);
            const r2 = await postJSON("/api/changelog", {project, component: comp, action: "first", text});
            const j2 = await r2.json();
            if (j2.error) return notify(j2.error, true);
            notify("CHANGELOG.md written; the next bump dates it");
            drawChangelog(pane, comp, j2);
          };
          return;
        }
        drawChangelog(pane, comp, j);
      }catch(e){ pane.textContent = "changelog: " + e; }
    });
    box.querySelectorAll("[data-verbump]").forEach(b => b.onclick = async () => {
      const part = b.dataset.verbump, comp = b.dataset.vercomp || "";
      const blk = all.find(x => (x.component || "") === comp);
      const to = blk?.next?.[part];
      // Staged, not done: no confirm here, because nothing has happened yet
      // and Save is the question. Pressing the same part again clears it,
      // which is how a misclick is undone without a dialog.
      verPending[comp] = verPending[comp] === part ? undefined : part;
      if (verPending[comp] === undefined) delete verPending[comp];
      drawVersion();
      nb.syncSave();
    });
    // Creating the first VERSION, and creating a component's. Both exist
    // because the file tools are denied on VERSION: without a sanctioned path
    // the tab would be telling the operator to do something no part of this
    // UI can do, which is how a guardrail turns into a thing people route
    // around.
    const start = el => {
      const f = el.closest(".verinit").querySelector(".vstart");
      const val = (f.value || "").trim();
      if (!/^\d+\.\d+\.\d+$/.test(val)){
        notify("a version is MAJOR.MINOR.PATCH, like 0.1.0", true);
        f.focus();
        return null;
      }
      return val;
    };
    box.querySelectorAll("[data-verinit]").forEach(b => b.onclick = async () => {
      const val = start(b);
      if (val === null) return;
      busy(b, "Setting");
      await postVersion({action: "init", value: val,
                         component: b.dataset.verinit || ""});
    });
    const add = box.querySelector("[data-veradd]");
    if (add) add.onclick = async () => {
      const val = start(add);
      if (val === null) return;
      const dir = add.closest(".verinit").querySelector(".vdir").value;
      busy(add, "Adding");
      await postVersion({action: "init", value: val, component: dir});
    };
    // Asked of the session rather than answered here, and then the tab gets
    // out of the way: the same shape as sending a step, because it is the
    // same thing: a question that wants a conversation, not a field filled in
    // behind the operator's back.
    // The fold opens the way every other fold on the page does: driven, not
    // the browser's instant snap. Same helper as a memory and a bug report.
    box.querySelectorAll("details.veradd > summary").forEach(sum => {
      sum.onclick = e => {
        e.preventDefault();
        slideDetails(sum.parentElement, !sum.parentElement.open);
      };
    });
    box.querySelectorAll("[data-verask]").forEach(b => b.onclick = async () => {
      const comp = b.dataset.verask === "@fold"
        ? b.closest(".verinit").querySelector(".vdir").value
        : (b.dataset.verask || "");
      busy(b, "Sending");
      try{
        const r = await postJSON("/api/version", {project, action: "ask", component: comp});
        const j = await r.json();
        if (j.error){ notify(j.error, true); b.disabled = false; return; }
        if (!j.sent){
          notify("Not sent: the session is busy. Press Enter in its tab when it is free.",
                 true);
        }
        startClaude(project, null);   // opens the tab, or goes to the one there
      }catch(e){ notify("ask: " + e, true); }
      // finally, not after the try: an exception on the way to the session
      // used to leave this dead, and a button that will not fire twice is
      // indistinguishable from one that did nothing.
      finally { b.disabled = false; }
    });
    // Staged like a bump, written by the foot's Save (docs/design-language.md,
    // Settings): picking the saved value back clears the stage.
    const pol = $("verPolicy");
    if (pol) pol.onchange = () => {
      verPolicyPending = pol.value === pol.dataset.was ? null : pol.value;
      drawVersion(); nb.syncSave();
    };
  }

  // "Ships something else from here?": the door to a component's own
  // number. Offered wherever candidate directories exist, INCLUDING on a
  // project with no version of its own yet: two products with different
  // maturities is exactly the state a fresh project can already be in, and
  // the two inits work in either order.
  function verAddFold(v){
    if (v.component || !(v.candidates || []).length) return "";
    return `
      <details class="veradd"${sectAttr("artifacts:veradd:" + project)}><summary>ships something else from here?</summary>
        <p class="verwhy">A directory with its own <code>VERSION</code> file is
          versioned on its own, like an extension beside an app.</p>
        <div class="verinit">
          <select class="vdir" aria-label="which directory">${
            v.candidates.map(c => `<option>${esc(c)}</option>`).join("")}</select>
          <input class="vstart" value="0.1.0" size="8" maxlength="20"
            inputmode="decimal" aria-label="starting version"
            pattern="[0-9]+\.[0-9]+\.[0-9]+">
          <button type="button" data-veradd>Give it its own version</button>
          <button type="button" data-verask="@fold"
            title="put the question to this project's Claude session, for
this directory">Send to Claude</button>
        </div>
      </details>`;
  }

  // The block for one VERSION file. Its NAME is not in here: the section
  // heading around it carries that, along with the number as its status.
  function verSection(v){
    const f = v.forms || {};
    const staged = verPending[v.component || ""];
    // What a window move costs, when this project is the one that owns the
    // window (the server decides that, from the files that move it). A
    // COMPONENT's version is its own and carries none of it.
    const cost = v.component ? null : ver?.window_cost;
    // Where the number here lives against the branch builds come from, and
    // where a staged bump would land: the server's sentences (version.lands),
    // so the row and bb version say the same thing. A bump on a branch
    // already merged, unpushed, read as the project's version here while
    // main still had the old one, and nothing on the row said so (B338).
    const lands = v.lands || {};
    const mark = (text, bad) => text ? `<div class="verln"><span></span><span class="vermark${
      bad ? " bad" : ""}">${esc(text)}</span></div>` : "";
    const line = (label, value, cls = "") => value
      ? `<div class="verln ${cls}"><span>${label}</span><code>${esc(value)}</code></div>`
      : "";
    // "running here" only where it is a comparison rather than a coincidence:
    // BB_VERSION is the image's, and the image is built from one repo. It is
    // also the line that catches "merged, therefore running", which has cost
    // this project an afternoon before.
    const stale = v.running && f.semver && v.running !== f.semver;
    // Which way round, because the two directions mean opposite things and
    // guessing gets it wrong half the time. The ordinal is the only orderable
    // part, which is the entire reason it exists.
    const ordOf = str => { const m = /-dev\.(\d+)/.exec(str || ""); return m ? +m[1] : null; };
    const mine = v.ordinal, theirs = ordOf(v.running);
    const which = !stale ? ""
      : (theirs != null && mine != null && theirs > mine)
        ? "the running build is newer than this checkout: pull"
      : (theirs != null && mine != null && theirs < mine)
        ? "this checkout is newer than the running build: it is not deployed yet"
        : "the running build and this checkout are different builds";
    const newest = (art?.artifacts || [])[0];
    const s = v.since || {};
    // Counts, no verdict. Roadmap items finished reads as a minor and fixes
    // alone read as a patch, but that judgment is the operator's: a
    // recommendation this side cannot justify is worse than none.
    const bits = [];
    if (s.commits != null) bits.push(`${s.commits} commit${s.commits === 1 ? "" : "s"}`);
    if (s.done) bits.push(`${s.done} roadmap item${s.done === 1 ? "" : "s"} done`);
    if (s.fixed) bits.push(`${s.fixed} bug${s.fixed === 1 ? "" : "s"} fixed`);
    if (v.unreleased) bits.push(`${v.unreleased} change${v.unreleased === 1 ? "" : "s"} logged`);
    // "building towards" until the tag exists, "released as" after: the two
    // gestures said in the label somebody reads first, because which of them
    // has happened is the question this block kept failing to answer.
    return (v.target
              ? line(v.released ? "released as" : "building towards", v.target)
              : line("version", "none yet: no VERSION file; Set one below"))
      + (v.released ? line("tag", v.tag) : "")
      + mark(lands.now, lands.bad)
      + (staged ? `<div class="verln"><span></span><span class="vermark">
           staged: ${esc(v.next[staged] || "")} on Save: ${esc(staged)}${
             v.unreleased ? `, dating ${v.unreleased} changelog entr${
               v.unreleased === 1 ? "y" : "ies"}`
             : `, with no changelog entries to date`}</span></div>` : "")
      + (staged ? mark(lands.staged, lands.staged_bad) : "")
      // What a MINOR bump costs everything else, said BEFORE Save rather than
      // discovered after it (B92): the minor is the compatibility window, so
      // moving it ends the Claude sessions on every project whose block is
      // from the old one and holds them until each is updated. The count is
      // the server's, from the blocks that actually exist.
      + (windowMove(staged, cost) ? `<div class="verln"><span></span>
           <span class="vermark bad">this moves the compatibility window from ${
             esc(cost.window)} to ${esc((v.next[staged] || "").split(".").slice(0, 2).join("."))
             }: sessions on ${cost.projects.length} project${cost.projects.length === 1 ? "" : "s"
             } end until each is updated from the bell</span></div>` : "")
      + line("a build now", f.semver)
      + (v.running ? line("running here", v.running, stale ? "" : "off") : "")
      + (stale ? `<div class="verln"><span></span><span class="vermark">${
           esc(which)}</span></div>` : "")
      + (newest ? line("last shipped", newest.name, "off") : "")
      + (v.warn ? `<div class="verln"><span></span><span class="vermark">${
           esc(v.warn)}</span></div>` : "")
      + (v.target ? `
        <p class="verwhy">${bits.length
          ? "since " + esc(v.target) + ": " + bits.join(" · ")
          : "nothing has landed since " + esc(v.target)}</p>
        <div class="actbar verbtns">
          ${["patch", "minor", "major"].map(pt => `
            <button type="button" data-verbump="${pt}" data-vercomp="${esc(v.component || "")}"
              class="${staged === pt ? "on" : ""}"
              title="${staged === pt
                ? "staged: Save writes VERSION and commits it; press again to unstage"
                : `stage ${esc(v.next[pt] || "")}; nothing is written until Save`}">
              ${pt[0].toUpperCase() + pt.slice(1)} → ${esc(v.next[pt] || "")}</button>`).join("")}
          <button type="button" data-verask="${esc(v.component || "")}"
            title="ask the session whether ${esc(v.target)} should move; it proposes and asks first">Send to Claude</button>
          ${v.prev && !v.sealed ? `
          <button type="button" data-verunbump="${esc(v.component || "")}"
            title="take the version back to ${esc(v.prev)}; ${esc(v.target)}'s changelog lines return to Unreleased">↩ ${esc(v.prev)}</button>` : ""}
          ${v.released ? "" : `
          <button type="button" data-verrelease="${esc(v.component || "")}"
            ${v.dirty ? "disabled" : ""}
            title="${v.dirty
              ? "there are uncommitted changes: commit or discard them first, so the tag marks what is in the commit"
              : `tag this commit ${esc(v.component ? v.component + "-v" + v.target : "v" + v.target)} and push the tag: `
                + "that is what releases " + esc(v.target)}"
            >Release ${esc(v.target)}</button>`}
          <button type="button" class="verlogbtn" data-verlog="${esc(v.component || "")}"
            title="what changed, for the people using it; a bump dates the lines so far">Changelog${
            v.unreleased ? ` (${v.unreleased} new)` : ""}</button>
        </div>
        ${v.component ? "" : verPolicyPicker(v)}
        <p class="verwhy">${v.released
          ? `Released: <code>${esc(v.tag)}</code> is on this commit, so a build of it
             is <code>${esc(v.target)}</code> exactly. Bump to start the next one.`
          : `<b>Bump</b> decides the number and closes the changelog under it;
             <b>Release</b> tags and pushes it. ${helpIcon(`Two steps. Until the release, a build reads ${
               v.target}-dev.${v.ordinal ?? "n"} rather than ${v.target}: the tag on the commit, pushed, is what says it happened.`)}`}</p>
        ${v.component ? "" : `<p class="verwhy">A bump is staged until Save, and is never pushed. ${
          helpIcon("Save writes and commits VERSION. Claude access limits what a session may change.")}</p>
        ${verAddFold(v)}`}` : `
        ${v.component ? "" : verPolicyPicker(v)}
        <div class="verln"><span>start at</span>
          <span class="verinit">
            <input class="vstart" value="0.1.0" size="8" maxlength="20"
              inputmode="decimal" aria-label="starting version"
              pattern="[0-9]+\.[0-9]+\.[0-9]+">
            <button type="button" data-verinit="${esc(v.component || "")}"
              title="write a VERSION file at this number and commit it">Set</button>
          </span></div>
        <div class="actbar verbtns">
          <button type="button" data-verask="${esc(v.component || "")}"
            title="ask the session what the version should be; it proposes and asks first">Send to Claude</button>
          <button type="button" data-verlog="${esc(v.component || "")}"
            title="entries logged before the first version wait here">Changelog${
            v.unreleased ? ` (${v.unreleased} new)` : ""}</button>
        </div>
        <p class="verwhy">No version yet. Setting one writes a
          <code>VERSION</code> file and commits it${v.unreleased
            ? `, dating the ${v.unreleased} logged change${
                v.unreleased === 1 ? "" : "s"} as its first section` : ""}.</p>
        ${verAddFold(v)}`);

  }

  // The one picker, drawn in both states of this tab. It used to be written
  // only into the has-a-version branch, so a project with no version had no
  // way to say who may give it one, which is the setting that matters most
  // at exactly that moment.
  function verPolicyPicker(v){
    return `<label class="verpol">
      <span>Claude access</span>
      <select id="verPolicy" data-was="${esc(v.policy)}"
        aria-label="what a Claude session may do with this project's version">
        ${(v.policies || []).map(o => `<option value="${esc(o)}"${
          o === (verPolicyPending ?? v.policy) ? " selected" : ""}>${
          esc(POLICY_LABEL[o] || o)}</option>`).join("")}
      </select>${verPolicyPending != null
        ? `<span class="vermark">staged: on Save</span>` : ""}
    </label>`;
  }

  async function postVersion(body, quiet){
    try{
      const r = await postJSON("/api/version", {project, ...body});
      const j = await r.json();
      if (j.error){ notify(j.error, true); }
      else if (j.bumped){
        if (!quiet) notify(`version ${j.bumped.was} → ${j.bumped.target}`);
        if (j.bumped.note) notify(j.bumped.note, true);
      }
      else if (j.unbumped) notify(`version returned: ${j.unbumped.was} → ${
        j.unbumped.target}: its changelog is back in Unreleased`);
      else if (j.created) notify(`${j.created.component || "this project"} `
                                 + `is now ${j.created.target}`);
      return j;
    }catch(e){ notify("version: " + e, true); }
    finally{ await loadVersion(); }
  }

  async function postArtifacts(body){
    try{
      const r = await postJSON("/api/artifacts", {project, ...body});
      const j = await r.json();
      if (j.error){ notify(j.error, true); }
    }catch(e){ notify("artifacts: " + e, true); }
    await loadArtifacts();
  }

  // This notebook's own filter state, so two notebooks in a split do not
  // share a search box's contents.

  return {loadArtifacts, loadVersion, drawVersion, postArtifacts, postVersion};
}
