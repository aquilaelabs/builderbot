// The notebook's Signing view: a project's Android keys (R106), in its Ship
// group after VMs (R103, the operator 22 Oct: a section of Settings was not
// where somebody looking for the keys a build is signed with looked). One
// classic script beside index.html (docs/nodes.md §13): one file per
// notebook view (R60). A factory makeNotebook calls per notebook, drawing its
// own markup into its own clone: nothing here is lent between two places.

"use strict";

// The two slots a named key has, with what each is for.
const SIGN_ROUTES = [
  ["play", "Play upload key",
   "For Google Play with Play App Signing, which can reset a lost upload key."],
  ["sideload", "Sideload signing key",
   "Signs a build handed out directly. Lose it and no update reaches an existing install: keep a copy offline."]];
const signFp = sha => sha ? `${sha.slice(0, 8)}…${sha.slice(-8)}` : "";
const fileB64 = f => new Promise((ok, bad) => {
  const r = new FileReader();
  r.onload = () => ok(String(r.result).split(",")[1] || "");
  r.onerror = () => bad(r.error);
  r.readAsDataURL(f);
});

// How the controller keeps a project's keys (R111 step 2), the Signing
// view's status line: sealed under the install's signing secret, kept open
// for want of one, or sealed under one this controller does not have.
const AT_REST = {
  sealed: "sealed on the controller under the install's signing secret",
  mixed: "being sealed under the install's signing secret",
  open: `<span class="warn">kept unsealed on the controller: SIGNING_SECRET in the secrets folder seals them</span>`,
  locked: `<span class="bad">sealed under a signing secret this controller does not have: set it as it was, or import each key's backup</span>`,
};

function nbSigningView({$, nb, project}){
  // Named keys (default first), each with a Play upload slot and a sideload
  // slot, and which of the project's apps (by package) signs with which key.
  // The controller keeps them and bb sign uses them on the node; the page
  // only ever sees aliases and fingerprints. An upload, a removal and a
  // mapping are staged behind their section's Save; Generate, Rotate,
  // Download backup and the backup password act on the press.
  let keys = null, map = {}, tool = false, why = "", mayBackup = false, locked = false, mayLock = false, rel = null;
  let nodeWhy = "";                             // what keeps the project's node from working on a key (signing.signer)
  let atRest = "";                              // sealed, open, mixed or locked (signing.at_rest)
  let draft = {}, mapDraft = {}, fresh = [], lockOpen = false, pw = {}, adding = false, gen = 0;
  let keyPick = "";                             // the key the chips picked, "" for all (R122)

  async function loadSigning(){
    const mine = ++gen;
    let j;
    try{
      j = await (await postJSON("/api/signing", {action: "list", project})).json();
    }catch(e){ viewGlance($("sgHint"), [], esc("signing: " + e)); return; }
    if (mine !== gen) return;
    if (j.error){
      // The server's own words, where the keys would be (R255 step 4).
      keys = null;
      viewGlance($("sgHint"), []);
      $("sgAdd").innerHTML = ""; $("sgActs").innerHTML = "";
      $("sgBox").innerHTML = `<div class="field"><div class="hint nbempty">${esc(j.error)}</div></div>`;
      return;
    }
    keys = j.keys || {}; map = j.map || {}; nodeWhy = j.node_why || ""; tool = !nodeWhy;
    why = j.why || ""; mayBackup = !!j.may_backup;
    locked = !!j.backup_locked; mayLock = !!j.may_lock; atRest = j.at_rest || "";
    rel = j.release || null;
    drawSigning();
  }

  // Every key named, the held ones and the ones New key added, default first.
  const keyNames = () => {
    const names = [...new Set([...Object.keys(keys || {}), ...fresh])];
    if (!names.includes("default")) names.unshift("default");
    return names;
  };
  const keyDrafts = key => Object.values(draft).filter(d => d.key === key && (d.remove || d.file));
  const mapCount = () => Object.keys(mapDraft).length;

  function slot(key, route, word, about){
    const k = (keys[key] || {})[route], d = draft[`${key}:${route}`] || {};
    const now = d.remove ? `${word}: removed when you Save`
      : d.file ? `${word}: ${esc(d.file.name)}, kept when you Save`
      : k ? `${word}: ${esc(k.alias)} <span class="dim">${esc(signFp(k.sha256))}${k.generated ? ", generated" : ""}</span>`
      : `${word}: none`;
    const never = k && !d.remove && !d.file && route === "sideload" && !k.backed_up;
    // Rotation (R106 step 7): what this key was rotated to or from, and the
    // keys it could hand an app to.
    const retired = route === "sideload" && k?.retired_for, rotated = route === "sideload" && k?.rotated_from;
    const targets = !why && route === "sideload" && k && !retired ? Object.entries(keys)
      .filter(([n, s]) => n !== key && s.sideload && !s.sideload.retired_for && !s.sideload.rotated_from).map(([n]) => n) : [];
    // What a role does not give is not drawn (the operator, 21 Oct): an
    // account that may not change the keys reads them.
    const acts = why ? "" : `
        ${locked || d.open ? `<button type="button" class="link" data-signopen>${d.open ? "Never mind" : k ? "Replace" : "Upload one"}</button>` : ""}
        ${!k && !d.open && tool && locked ? `<button type="button" class="link" data-signgen>Generate</button>` : ""}
        ${k && mayBackup ? (locked
          ? `<button type="button" class="link" data-signbackuppw>Download backup</button>`
          : `<a class="link" data-signbackup href="/api/signing-backup?project=${encodeURIComponent(project)}&key=${encodeURIComponent(key)}&route=${route}" download>Download backup</a>`) : ""}
        ${k && !retired ? `<button type="button" class="link" data-signremove>${d.remove ? "Keep it after all" : "Remove"}</button>` : ""}
        ${targets.length ? `<select data-rotateto aria-label="the key to rotate ${esc(key)} to">${
          targets.map(n => `<option>${esc(n)}</option>`).join("")}</select>
        <button type="button" class="link" data-rotate>Rotate to it</button>` : ""}`;
    return `<div class="rnsign" data-key="${esc(key)}" data-route="${route}">
      <div>${now}</div>
      <div class="sub dim">${esc(about)}${k && !d.remove && !d.file
        ? ` ${k.backed_up ? `Backed up ${esc(ago(k.backed_up))}.` : "Not backed up yet."}` : ""}</div>
      ${never ? `<div class="notice bad">Never backed up: ${mayBackup ? "download a copy and keep it offline"
        : "an administrator on this project downloads a copy to keep offline"}, since losing it is final.</div>` : ""}
      ${retired ? `<div class="sub">Retired: rotated to ${esc(k.retired_for)}. Kept, since the proof and every device before Android 9 still need it.</div>` : ""}
      ${rotated ? `<div class="sub">Rotated from ${esc(k.rotated_from)}: Android 9 and newer see this key, older devices still see ${esc(k.rotated_from)}.</div>` : ""}
      ${k && !d.remove && pw[`${key}:${route}`] ? `<div class="rnsignbar actbar">
        <input type="password" data-signbackuppass autocomplete="current-password" placeholder="the backup password" aria-label="the backup password">
        <button type="button" class="link" data-signbackupgo>Download</button></div>` : ""}
      ${d.open ? `<div class="rnsignform">
        <input type="file" data-signfile accept=".jks,.p12,.pfx,.keystore" aria-label="${esc(word)} keystore">
        <input type="password" data-signpass autocomplete="new-password" placeholder="keystore password" aria-label="keystore password">
        <input data-signalias autocomplete="off" spellcheck="false" placeholder="alias, when it holds several" aria-label="key alias">
        <input type="password" data-signkeypass autocomplete="new-password" placeholder="key password, if not the same" aria-label="key password">
      </div>` : ""}
      ${acts.trim() ? `<div class="rnsignbar actbar">${acts}</div>` : ""}
    </div>`;
  }

  function drawSigning(){
    if (!keys) return;
    const names = keyNames();
    const held = Object.values(keys).filter(s => SIGN_ROUTES.some(([r]) => s[r])).length;
    // The glance (R109): the keys held and the apps mapped to one, none
    // while it holds no key, whose empty state is said where the keys are.
    const mappedN = Object.values({...map, ...mapDraft}).filter(k => k !== null).length;
    // ...and under them how the controller keeps them (R111 step 2).
    viewGlance($("sgHint"), !held ? [] : [
      {label: held === 1 ? "key" : "keys", value: held},
      {label: mappedN === 1 ? "app" : "apps", value: mappedN, omit: !mappedN}],
      !held ? "" : AT_REST[atRest] || "");
    // Import a backup and New key, the view's adds, the control row's
    // actions with New key the primary (a-notebook/views, R109), the form
    // either opens unrolling under the row.
    $("sgActs").innerHTML = why ? "" : `<button type="button" id="sgImp" data-add="import" aria-expanded="${adding === "import"}"${
        locked ? "" : ` disabled title="no key can be added until the backups have a password"`}><span class="lng">Import a backup</span><span class="shrt">Import</span></button><button type="button" class="primary" id="sgNew" data-add="key" aria-expanded="${adding === "key"}">New key</button>`;
    $("sgAdd").innerHTML = why ? ""
      : adding === "key" ? `<div class="field"><div class="addbar actbar ctlrow">
          <input id="sgNewName" autocomplete="off" spellcheck="false" placeholder="name, e.g. watch" aria-label="a new key's name">
          <button type="button" id="sgNewGo">Add it</button><button type="button" id="sgAddCancel">Cancel</button></div></div>`
      // A backup brought back (R103, the operator 22 Oct): Download
      // backup's zip carries its alias, and its password unless it was
      // wrapped under a project's backup password (R111), which is then
      // typed here, as a bare keystore's is; the key and the slot default
      // to the backup's.
      : adding === "import" ? `<div class="field"><div class="rnsignform">
          <input type="file" id="sgImpFile" accept=".zip,.jks,.p12,.pfx,.keystore" aria-label="the backup">
          <input id="sgImpKey" autocomplete="off" spellcheck="false" placeholder="key name, or the backup's" aria-label="the key it becomes">
          <select id="sgImpRoute" aria-label="the slot it goes in"><option value="">the slot the backup names</option>${
            SIGN_ROUTES.map(([r, w]) => `<option value="${r}">${w}</option>`).join("")}</select>
          <input type="password" id="sgImpPass" autocomplete="off" placeholder="the backup password it was made under, or a keystore's own" aria-label="the backup's or the keystore's password">
          <div class="sub dim">A backup from a project with a backup password is wrapped under that password: type it here. A keystore on its own needs the password it was made with.</div>
          <div class="actbar"><button type="button" id="sgAddCancel">Cancel</button><button type="button" class="primary" id="sgImpGo" disabled>Import</button></div>
        </div></div>`
      : "";
    // The backup password (the operator, 1 Oct): the project's owner's to
    // set, and every download's to give, BuilderBot's owner's included.
    const lock = `<div class="field"><div class="rnsign rnsignlock">
      <div>Backup password: ${locked ? "set" : "none"}</div>
      <div class="sub dim">${locked ? "Every key backup asks for it, whoever downloads it."
        : "Every key backup will ask for it, whoever downloads it."}${mayLock ? "" : " The project's owner sets it."}</div>
      ${locked ? "" : `<div class="notice warn">No key can be added or made until it has one${mayLock ? ": set it first" : ""}.</div>`}
      ${mayLock && lockOpen ? `<div class="rnsignform">
        ${locked ? `<input type="password" id="sgLockCur" autocomplete="current-password" placeholder="the backup password now" aria-label="the backup password now">` : ""}
        <input type="password" id="sgLockNew" autocomplete="new-password" placeholder="${locked ? "a new one, or empty to remove it" : "at least ten characters"}" aria-label="the new backup password">
        <input type="password" id="sgLockAgain" autocomplete="new-password" placeholder="the new one again" aria-label="the new backup password again">
        <div class="rnsignbar actbar"><button type="button" class="link" id="sgLockGo" disabled>${locked ? "Change it" : "Set it"}</button></div>
      </div>` : ""}
      ${mayLock ? `<div class="rnsignbar actbar"><button type="button" class="link" id="sgLockOpen">${
        lockOpen ? "Never mind" : locked ? "Change or remove" : "Set a backup password"}</button></div>` : ""}
    </div></div>`;
    // Each key a section with its own Save and Revert, and the apps one.
    names.forEach(key => nb.stage(`signing:key:${key}`, {
      count: () => keyDrafts(key).length,
      what: () => `the staged changes to ${key === "default" ? "the default key" : key}`,
      save: () => saveKey(key),
      revert: () => { for (const k of Object.keys(draft)) if (draft[k].key === key) delete draft[k];
                      fresh = fresh.filter(n => n !== key); drawSigning(); }}));
    nb.stage("signing:apps", {
      count: mapCount,
      what: () => `${mapCount()} staged app mapping${mapCount() === 1 ? "" : "s"}`,
      save: saveApps,
      revert: () => { mapDraft = {}; drawSigning(); }});
    const maps = {...map, ...mapDraft};
    const mapped = Object.entries(maps).filter(([, k]) => k !== null);
    const apps = `<div class="field">
      <div class="sub dim">Which app signs with which key, by its package; one not listed signs with the default key.</div>
      ${mapped.map(([pkg, k]) => `<div class="rninvite" data-pkg="${esc(pkg)}">
        <code>${esc(pkg)}</code> <span class="dim">signs with</span> <b>${esc(k)}</b>
        ${why ? "" : `<button type="button" class="link" data-unmap>Remove</button>`}</div>`).join("")}
      ${why ? "" : `<div class="rninvitebar"><input id="sgMapPkg" autocomplete="off" spellcheck="false" placeholder="com.example.app"
          aria-label="an app's package"><select id="sgMapKey" aria-label="the key it signs with">${
          names.map(k => `<option>${esc(k)}</option>`).join("")}</select>
        <button type="button" class="link" id="sgMapGo">Map it</button></div>`}</div>`;
    // Releases (R106): a release's APK is built unsigned in CI and signed
    // on the project's node with the sideload key its app maps to; which key that is, what
    // would stop it, and how the newest went.
    const r = rel || {};
    const relBody = !r.wanted
      ? `<div class="field"><div class="sub dim">This project's workflows hand over no unsigned APK, so BuilderBot signs none of its releases.
          A workflow that uploads its unsigned release APK as an artifact named <code>bb-release-apk-TAG</code> has it signed
          on the project's node with the sideload key and attached to the release, with no key or password on GitHub.</div></div>`
      : `<div class="field" id="sgRel">
          ${(r.keys || []).map(k => `<div class="rninvite" data-relkey="${esc(k.key)}">${k.package ? `<code>${esc(k.package)}</code> ` : ""}<span class="dim">releases sign with</span>
            <b>${esc(k.key)}</b> <span class="dim">${esc(signFp(k.sha256))}${k.rotated_from ? `, rotated from ${esc(k.rotated_from)}` : ""}</span></div>`).join("")}
          ${r.why ? `<div class="notice warn">${esc(r.why)}</div>` : ""}
          ${(r.failed || []).map(f => `<div class="notice bad">${esc(f.tag)}: ${esc(f.why)}${f.at ? ` <span class="dim">${esc(ago(f.at))}</span>` : ""}</div>`).join("")}
          ${(r.signed || []).slice(0, 3).map(x => `<div class="sub">${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.tag)}</a>` : esc(x.tag)}:
            ${esc((x.files || []).join(", "))} signed with ${esc(x.key)} <span class="dim">${esc(signFp(x.cert))}, ${esc(ago(x.at))}</span></div>`).join("")}
          <div class="sub dim">The release's APK is built unsigned by its workflow and signed on ${r.node ? `the project's node, ${esc(r.node)}` : "the project's node"}, never in CI: no keystore or password is a GitHub secret.</div>
          ${why ? "" : `<div class="rnsignbar actbar"><button type="button" class="link" id="sgRelGo">Look for unsigned APKs now</button></div>`}
        </div>`;
    const relStatus = !r.wanted ? "off" : r.why ? "blocked" : (r.failed || []).length ? "failed"
      : (r.keys || []).map(k => k.key).filter((k, i, a) => a.indexOf(k) === i).join(", ") || "ready";
    const keyStatus = key => {
      const s = keys[key] || {}, n = SIGN_ROUTES.filter(([r]) => s[r]).length;
      return n ? `${n} of 2` : "none";
    };
    $("sgBox").innerHTML =
      (why ? `<div class="field"><div class="hint">${esc(why)}</div></div>` : "")
      // A key is checked and made on the project's node, never here: what
      // keeps that node from it is said in its words (B232).
      + (!tool && !why ? `<div class="field"><div class="hint" id="sgNode">${esc(nodeWhy)}</div></div>` : "")
      + (!held && !why ? `<div class="field"><div class="hint nbempty">No keys yet: bb sign signs this project's builds on its node with the keys kept here, and a session never sees one.</div></div>` : "")
      + docSection("signing", "lock", "Backup password", locked ? "set" : "none", lock, {cls: locked ? "" : "warn"})
      // The keys are the project's, as many as it has: big chips pick one,
      // the small pills are for the view's own sections (R122).
      + chipBar(names.map(key => ({key, label: key === "default" ? "Default key" : key, count: null})),
                names.includes(keyPick) ? keyPick : "", "data-sgkey")
      + names.filter(key => !keyPick || !names.includes(keyPick) || key === keyPick)
          .map(key => docSection("signing", `key:${key}`, key === "default" ? "Default key" : `Key: ${key}`,
          keyStatus(key), `<div class="field">${SIGN_ROUTES.map(([route, word, about]) => slot(key, route, word, about)).join("")}</div>`
            + (why ? "" : nb.sectBar(`signing:key:${key}`)), {item: true})).join("")
      + docSection("signing", "apps", "Apps", mapped.length ? `${mapped.length}` : "none",
          apps + (why ? "" : nb.sectBar("signing:apps")))
      + docSection("signing", "releases", "Releases", relStatus, relBody,
          {cls: r.wanted && (r.why || (r.failed || []).length) ? "warn" : ""});
    wireSections($("sgBox"));
    $("sgBox").querySelectorAll("[data-sgkey]").forEach(c => c.onclick = () => { keyPick = c.dataset.sgkey; drawSigning(); });
    wire();
    nb.syncSave();
  }

  function wire(){
    const box = $("sgBox"), add = $("sgAdd");
    for (const row of box.querySelectorAll(".rnsign[data-key]")){
      const key = row.dataset.key, route = row.dataset.route;
      const d = draft[`${key}:${route}`] = draft[`${key}:${route}`] || {key, route};
      const on = (sel, fn) => { const b = row.querySelector(sel); if (b) b.onclick = () => fn(b); };
      on("[data-signopen]", () => {
        d.open = !d.open;
        if (!d.open){ delete d.file; d.pass = d.alias = d.keypass = ""; }
        else d.remove = false;
        drawSigning();
      });
      on("[data-signgen]", async b => {
        if (route === "sideload" && !await askYes(`Make a new sideload signing key named ${key}? `
              + "Once a build signed with it is out, it is that app's identity for good: download a backup straight after."))
          return;
        b.disabled = true;
        const j = await (await postJSON("/api/signing", {action: "generate", project, key, route})).json();
        if (j.error){ b.disabled = false; return notify(j.error, true); }
        notify(`${key}: a ${route === "play" ? "Play upload" : "sideload signing"} key was made; download a backup`);
        fresh = fresh.filter(n => n !== key);
        loadSigning();
      });
      on("[data-rotate]", async b => {
        const to = row.querySelector("[data-rotateto]").value;
        if (!await askYes(`Rotate ${key}'s sideload key to ${to}? Builds then go out signed with both and a proof: `
              + `Android 9 and newer move to ${to}, older devices keep checking ${key}, and ${key} is kept for good.`)) return;
        b.disabled = true;
        const j = await (await postJSON("/api/signing", {action: "rotate", project, from: key, to})).json();
        if (j.error){ b.disabled = false; return notify(j.error, true); }
        notify(`${key} is rotated to ${to}: the apps it signed now sign with ${to} and the proof`);
        loadSigning();
      });
      on("[data-signremove]", () => { d.remove = !d.remove; if (d.remove){ d.open = false; delete d.file; delete pw[`${key}:${route}`]; } drawSigning(); });
      on("[data-signbackuppw]", () => { pw[`${key}:${route}`] = !pw[`${key}:${route}`]; drawSigning(); });
      on("[data-signbackupgo]", async b => {
        const pass = row.querySelector("[data-signbackuppass]").value;
        b.disabled = true;
        const r = await postJSON("/api/signing-backup", {project, key, route, password: pass});
        if (!r.ok){ b.disabled = false; return notify((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`, true); }
        const fname = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || `${project}-${key}-${route}`;
        const a = document.createElement("a");
        a.href = URL.createObjectURL(await r.blob()); a.download = fname;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 10000);
        delete pw[`${key}:${route}`];
        loadSigning();
      });
      const bk = row.querySelector("[data-signbackup]");
      if (bk) bk.onclick = () => setTimeout(loadSigning, 1500);
      const f = row.querySelector("[data-signfile]");
      if (f){
        f.onchange = () => { d.file = f.files[0] || null; nb.syncSave(); };
        for (const [sel, k] of [["[data-signpass]", "pass"], ["[data-signalias]", "alias"], ["[data-signkeypass]", "keypass"]]){
          const el = row.querySelector(sel);
          el.value = d[k] || "";
          el.oninput = () => { d[k] = el.value; };
        }
      }
    }
    const rg = $("sgRelGo");
    if (rg) rg.onclick = () => pressing(rg, async () => {
      const j = await (await postJSON("/api/signing", {action: "release-sign", project})).json();
      if (j.error) return notify(j.error, true);
      notify(`${projLabel(project)}: looking for unsigned release APKs to sign`);
      setTimeout(loadSigning, 4000);
    });
    const lo = $("sgLockOpen");
    if (lo) lo.onclick = () => { lockOpen = !lockOpen; drawSigning(); };
    const lg = $("sgLockGo");
    // Wakes once what it sends makes sense (the operator, 18 Oct): the two
    // new ones alike and a password in them, or, with one set, both empty to
    // take it off; and the one now typed when there is one.
    const lockReady = () => {
      const cur = $("sgLockCur")?.value || "", nw = $("sgLockNew")?.value || "", again = $("sgLockAgain")?.value || "";
      return nw === again && (nw || locked) && (!locked || cur);
    };
    if (lg) ["sgLockCur", "sgLockNew", "sgLockAgain"].forEach(id => {
      const el = $(id);
      if (el) el.oninput = () => { lg.disabled = !lockReady(); };
    });
    if (lg) lg.onclick = async () => {
      const cur = $("sgLockCur")?.value || "", nw = $("sgLockNew").value, again = $("sgLockAgain").value;
      if (nw !== again) return notify("the two new passwords differ", true);
      if (!nw && !locked) return notify("type a password to set", true);
      lg.disabled = true;
      const j = await (await postJSON("/api/signing", {action: "backup-password", project, current: cur, new: nw})).json();
      if (j.error){ lg.disabled = false; return notify(j.error, true); }
      notify(j.backup_locked ? `${projLabel(project)}'s key backups now ask for the password` : `${projLabel(project)}'s key backups no longer ask for a password`);
      lockOpen = false;
      loadSigning();
    };
    const nw = $("sgNew");
    if (nw) nw.onclick = () => { adding = "key"; drawSigning(); add.querySelector("#sgNewName")?.focus(); };
    const im = $("sgImp");
    if (im) im.onclick = () => { adding = "import"; drawSigning(); };
    const nc = add.querySelector("#sgAddCancel");
    if (nc) nc.onclick = () => { adding = false; drawSigning(); };
    const ig = add.querySelector("#sgImpGo"), file = add.querySelector("#sgImpFile");
    if (file) file.onchange = () => { ig.disabled = !file.files[0]; };
    if (ig) ig.onclick = async () => {
      const f = file.files[0];
      if (!f) return;
      const name = add.querySelector("#sgImpKey").value.trim().toLowerCase();
      if (name && !/^[a-z0-9][a-z0-9-]{0,31}$/.test(name)) return notify("a key's name is lowercase letters, digits and dashes", true);
      await pressing(ig, async () => {
        const j = await (await postJSON("/api/signing", {action: "import", project, key: name,
          route: add.querySelector("#sgImpRoute").value, password: add.querySelector("#sgImpPass").value,
          filename: f.name, backup: await fileB64(f)})).json();
        if (j.error) return notify(j.error, true);
        const k = j.key || {};
        notify(`${projLabel(project)}: ${k.key || "the key"}'s ${(SIGN_ROUTES.find(([r]) => r === k.route) || [])[1] || "key"} imported (${signFp(k.sha256)})`);
        adding = false;
        fresh = fresh.filter(n => n !== k.key);
        loadSigning();
      });
    };
    const ng = add.querySelector("#sgNewGo");
    if (ng) ng.onclick = () => {
      const n = add.querySelector("#sgNewName").value.trim().toLowerCase();
      if (!/^[a-z0-9][a-z0-9-]{0,31}$/.test(n)) return notify("a key's name is lowercase letters, digits and dashes", true);
      if (!keyNames().includes(n)) fresh.push(n);
      adding = false;
      drawSigning();
    };
    const mg = $("sgMapGo");
    if (mg) mg.onclick = () => {
      const pkg = $("sgMapPkg").value.trim();
      if (!/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$/.test(pkg)) return notify("a package name looks like com.example.app", true);
      mapDraft[pkg] = $("sgMapKey").value;
      drawSigning();
    };
    box.querySelectorAll("[data-unmap]").forEach(b => b.onclick = () => {
      const pkg = b.closest("[data-pkg]").dataset.pkg;
      if (map[pkg]) mapDraft[pkg] = null; else delete mapDraft[pkg];
      drawSigning();
    });
  }

  // A key section's Save: its uploads and removals, in order. A message when
  // they landed; null, the draft kept and the reason said, when one was
  // refused or is not ready to send.
  async function saveKey(key){
    const mine = Object.values(draft).filter(d => d.key === key);
    const stop = msg => { notify(msg, true); return null; };
    if (mine.some(d => d.open && !d.file && (d.pass || d.alias)))
      return stop("pick the keystore file for the key whose password you typed");
    if (mine.some(d => d.file && !d.pass))
      return stop("type the keystore's password: a key is checked with it before it is kept");
    for (const d of mine){
      const word = (SIGN_ROUTES.find(([r]) => r === d.route) || [])[1] || d.route;
      let body = null;
      if (d.remove) body = {action: "remove", project, key: d.key, route: d.route};
      else if (d.file) body = {action: "put", project, key: d.key, route: d.route, keystore: await fileB64(d.file),
                               password: d.pass || "", alias: (d.alias || "").trim(), key_password: d.keypass || ""};
      if (!body) continue;
      const j = await (await postJSON("/api/signing", body)).json();
      if (j.error) return stop(`${d.key} ${word}: ${j.error}`);
      delete draft[`${d.key}:${d.route}`];
    }
    fresh = fresh.filter(n => n !== key);
    await loadSigning();
    return `${projLabel(project)}: signing keys`;
  }
  async function saveApps(){
    for (const [pkg, key] of Object.entries(mapDraft)){
      const j = await (await postJSON("/api/signing", {action: "map", project, package: pkg, key: key || ""})).json();
      if (j.error){ notify(`${pkg}: ${j.error}`, true); return null; }
      delete mapDraft[pkg];
    }
    await loadSigning();
    return `${projLabel(project)}: app mappings`;
  }
  // For the notebook's leave and close questions.
  const signStagedCount = () => Object.values(draft).filter(d => d.remove || d.file).length + mapCount();
  function signClearStaged(){ draft = {}; mapDraft = {}; fresh = []; adding = false; drawSigning(); }

  return {loadSigning, signStagedCount, signClearStaged};
}
