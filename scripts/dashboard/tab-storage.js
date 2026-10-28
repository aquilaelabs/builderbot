// The Storage tab (R169): what a node's disks hold, and whose. One node at
// a time, picked in the bar like Toolchains (the node-switcher rule; the
// operator, 11 Oct): a state row saying when it was measured, its
// filesystems as a meter stack, its stores and Docker's share, then each
// project's folders on it (the synced copy, the build cache, artifacts, a
// dev instance's data, emulators, the accounts' build caches), largest
// first, with every project this account may not see folded into one
// line. The numbers are the agent's hourly walk, said with their age;
// Measure now asks for a fresh one, which the next hello brings.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/storage, read when the tab opens and after Measure now; redrawn on
// the nodes revision, since a hello carries a new walk.

"use strict";

let storageList = null;          // last answer, or null before the first
let storageErr = "";
let storageRev = 0;
let storageMay = false;          // whether this account may measure now
let storageNode = "";            // the node the tab shows
let storageDisk = "";            // the disk its chips picked, "" for all (R122)

function openStorageTab(node){
  if (node) storageNode = node;
  openTab({kind: "storage", arg: "__storage", label: "Storage"});
}

async function loadStorage(){
  try{
    const j = await (await bootFetch("/api/storage")).json();
    storageErr = j.error || "";
    storageList = j.nodes || [];
    storageMay = !!j.may_measure;
  }catch(e){
    storageErr = String(e);
    storageList = storageList || [];
  }
  storageRev++;
  if (tabs.some(t => t.kind === "storage")) drawPanes();
}

// The node the tab opens on: the one it showed last (remembered in this
// browser), else the first in the answer, else nothing.
function storagePick(){
  const have = storageList || [];
  let want = storageNode;
  if (!have.some(n => n.node === want)){
    try{ want = localStorage.getItem("bb.stnode") || ""; }catch(e){ want = ""; }
  }
  if (!have.some(n => n.node === want)) want = have[0]?.node || "";
  storageNode = want;
  return have.find(n => n.node === want) || null;
}

// MB as a person reads it: TB above ten million, GB from one (a decimal
// under a hundred), MB below, "?" for unmeasured. One unit per view where
// it can be: the meters said GB while the rows under them said 7737 MB.
const sgb = mb => mb === null || mb === undefined ? "?"
  : mb >= 10485760 ? (mb / 1048576).toFixed(1) + " TB"
  : mb >= 1024 ? (mb / 1024).toFixed(mb >= 102400 ? 0 : 1) + " GB" : Math.round(mb) + " MB";

// Everything BuilderBot holds on the node, one item each: the stores, the
// synced copies (their size is the projects' workspace column, summed),
// the accounts' homes and Docker's data root. Each names the filesystem it
// sits on, which is what groups it under a meter below.
function storageHeld(n){
  const items = Object.entries(n.stores || {}).map(([role, st]) => ({
    name: `${role} store`, path: st.path, fs: st.fs || "", slow: !!st.slow, mb: st.slow ? null : (st.used_mb || 0)}));
  if (n.workspace?.path){
    const ws = [...(n.projects || []), n.other || {}].reduce((a, p) => a + (p.workspace || 0), 0);
    items.push({name: "synced copies", path: n.workspace.path, fs: n.workspace.fs || "", mb: ws, note: "per project below"});
  }
  if (n.homes?.path) items.push({name: "the accounts' homes", path: n.homes.path, fs: n.homes.fs || "", mb: n.homes.mb || 0,
                                 note: "their build caches per project below"});
  const dk = n.docker || {};
  if (dk.kinds?.length){
    const total = dk.kinds.reduce((a, k) => a + (k.mb || 0), 0);
    const recl = dk.kinds.reduce((a, k) => a + (k.reclaimable_mb || 0), 0);
    // The one number in Docker's share a person acts on is what a prune
    // would free; the kind-by-kind list (images 3095 MB (7), ...) is the
    // Docker tab's to tell.
    items.push({name: "Docker", path: dk.root || "its data root", fs: dk.fs || "", mb: total,
                note: recl ? `${sgb(recl)} of it reclaimable` : "", prune: recl ? n.node : ""});
  }
  return items;
}

function storageRow(h){
  return `<div class="row"><div class="grow"><div class="name">${esc(h.name)} <span class="dim">· ${esc(h.path)}</span></div>
      <div class="sub">${h.mb === null ? "not measured in time" : sgb(h.mb)}${h.note ? `; ${esc(h.note)}` : ""}${
        // ...and the way to it: the Containers page on this node with its
        // Images and volumes open, where the prunes are.
        h.prune ? `: <a href="#" data-stprune="${esc(h.prune)}">prune on the Containers page</a>` : ""}</div></div></div>`;
}

// What BuilderBot could free on a filesystem (R123 step 4): its projects'
// phones, its build caches and Docker's reclaimable, where they sit on it.
function storageFreeable(n, fs){
  const on = path => fs.path === path || (path || "").startsWith(fs.path === "/" ? "/" : fs.path + "/");
  const phones = (n.phones || []).filter(p => !p.running).reduce((a, p) => a + (p.mb || 0), 0);
  const builds = (n.projects || []).reduce((a, r) => a + (r.builds || 0), 0);
  const cache = n.stores?.cache && n.stores.cache.fs === fs.path
    ? (n.projects || []).reduce((a, r) => a + (r.cache || 0), 0) : 0;
  const dk = n.docker || {};
  const docker = dk.fs === fs.path ? (dk.kinds || []).reduce((a, k) => a + (k.reclaimable_mb || 0), 0) : 0;
  const home = n.homes?.fs === fs.path || on(n.homes?.path || "");
  // Each named with the page that frees it: this page only measures (the
  // operator, 23 Oct).
  const parts = [[home ? phones : 0, "phones not running (the Emulator page)"],
                 [(home ? builds : 0) + cache, "build caches (Clear cache on the node's row on the Nodes page)"],
                 [docker, "Docker's reclaimable (the Containers page)"]].filter(([mb]) => mb > 0);
  return parts.length ? `${sgb(parts.reduce((a, [mb]) => a + mb, 0))} of it can be freed: ${
    andList(parts.map(([mb, what]) => `${what.replace(/ \(/, ` ${sgb(mb)} (`)}`))}` : "";
}

// A list of names as a sentence: "cache, artifacts and appdata".
function andList(xs){
  return xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

// One picture per filesystem (R203): its meter, then what BuilderBot holds
// on it, largest first, with the stores holding nothing folded into one
// line. A flat list of nine stores under a separate meter stack said 37.8
// TB used above rows adding up to 10 GB, and left the reader to join them.
function storageDisks(n){
  const fss = n.filesystems || [];
  const held = storageHeld(n);
  if (!fss.length) return `<div class="empty">no filesystem measured yet</div>`;
  const block = (fs, mine) => {
    const some = mine.filter(h => h.mb === null || h.mb > 0).sort((a, b) => (b.mb || 0) - (a.mb || 0));
    const none = mine.filter(h => h.mb === 0);
    const ours = some.reduce((a, h) => a + (h.mb || 0), 0);
    const pct = fs.total_mb ? (fs.used_mb || 0) / fs.total_mb * 100 : 0;
    const also = fs.also?.length ? `, also at ${fs.also.join(", ")}` : "";
    // Each filesystem a card of its own (R218 step 47, the operator 18 Oct):
    // its mount the heading, used of its size the status, then its meter,
    // what of it is BuilderBot's and the rows of what that is.
    return docSection("storage", `fs:${fs.path}`, fs.path, `${sgb(fs.used_mb)} of ${sgb(fs.total_mb)}`,
      `<div class="field stdisk"><div class="ndmeters">${
        // "used": the card's heading already names the filesystem.
        meter("used", pct, `${sgb(fs.used_mb)} / ${sgb(fs.total_mb)}`,
              `${fs.source} (${fs.type}${fs.ro ? ", read-only" : ""})${also}`)}</div>${
        mine.length ? `<div class="sub">${ours ? `${sgb(ours)} of it is BuilderBot's` : "nothing of it is BuilderBot's yet"}</div>` : ""}${
        pct >= 90 && storageFreeable(n, fs) ? `<div class="sub warn">${esc(storageFreeable(n, fs))}.</div>` : ""}</div>${
      some.map(storageRow).join("")}${
      none.length ? `<div class="row stnone"><div class="grow"><div class="sub">${esc(andList(none.map(h => h.name)))} hold${none.length === 1 ? "s" : ""} nothing yet</div></div></div>` : ""}`,
      {cls: pct >= 92 ? "bad" : pct >= 80 ? "warn" : "", item: true});
  };
  // The disks are the node's, as many as it has: big chips pick one (R122),
  // where small pills listed them as if they were the page's sections.
  const off = held.filter(h => !fss.some(fs => fs.path === h.fs));
  const keys = [...fss.map(fs => fs.path), ...(off.length ? ["elsewhere"] : [])];
  if (storageDisk && !keys.includes(storageDisk)) storageDisk = "";
  const chips = chipBar([...fss.map(fs => ({key: fs.path, label: fs.path, count: null})),
                         ...(off.length ? [{key: "elsewhere", label: "Elsewhere", count: null}] : [])],
                        storageDisk, "data-stdisk");
  const out = fss.filter(fs => !storageDisk || storageDisk === fs.path).map(fs => block(fs, held.filter(h => h.fs === fs.path)));
  if (off.length && (!storageDisk || storageDisk === "elsewhere"))
    out.push(docSection("storage", "fs:elsewhere", "Elsewhere", "not measured", off.map(storageRow).join(""), {item: true}));
  return chips + out.join("");
}

// The controller's own machine's disks (R162 step 1), as its census lists
// them: each by name, model, size, serial, kind and what it holds, with
// SMART's health, temperature and hours where the machine has smartctl;
// the system disk marked. Read before anything is written to one; the
// pools and the shares come next on this page.
function storageMachineDisks(n){
  if (!n.own) return "";
  const disks = n.disks || [];
  const body = !disks.length ? `<div class="empty">No disk reported yet${n.live ? ": the next check-in brings them" : ": its agent is not dialing in"}.</div>`
    : (() => {
      const cols = [{label: "Disk"}, {label: "Model"}, {label: "Size", w: "6.5rem"}, {label: "Serial"}, {label: "Health", w: "9rem"}, {label: "Holds"}];
      return tblWrap(cols, disks.map(d => {
        const sm = d.smart || {};
        const health = [sm.health === "failing" ? `<span class="pill bad">failing</span>` : sm.health === "ok" ? `<span class="pill ok">ok</span>` : "",
                        sm.temp_c !== undefined ? `${sm.temp_c} °C` : "", sm.hours !== undefined ? `${Math.round(sm.hours / 24)} d on` : ""].filter(Boolean).join(" · ") || "<span class=\"dim\">no SMART</span>";
        const holds = d.parts?.length ? d.parts.map(p => `${esc(p.name)}: ${esc(p.holds)}`).join("<br>") : esc(d.holds || "nothing");
        return `<div class="row${sm.health === "failing" ? " bad" : ""}" data-disk="${esc(d.name)}">${tblLine(cols, [
          `<span class="name">${esc(d.name)}</span>${d.system ? ` <span class="tag ndown">system</span>` : ""}${d.removable ? ` <span class="pill">removable</span>` : ""}`,
          esc(d.model || "unnamed"), esc(humanBytes((d.size_mb || 0) * 1048576)), `<code>${esc(d.serial || "none")}</code>`,
          health, `${holds}<div class="sub dim">${esc([d.ssd ? "solid state" : "spinning", d.tran].filter(Boolean).join(" · "))}</div>`])}</div>`;
      }).join(""), "stdisks");
    })();
  const failing = disks.filter(d => d.smart?.health === "failing").length;
  return docSection("storage", "disks", "Disks", disks.length ? `${disks.length}${failing ? `, ${failing} failing` : ""}` : "", body, {cls: failing ? "bad" : ""});
}

// The controller's own machine's shares (R162 step 1): each as BuilderBot's
// own two files say it (the path, SMB with its users or as a guest, NFS
// with its clients), with Remove; and a form for a new one, every press a
// system job the root agent runs, which writes the files whole and tells
// Samba and NFS to read again. The SMB password an account sets is R164's.
function storageShares(n){
  if (!n.own) return "";
  const admin = !!state?.can?.admin && n.may_measure;
  const why = !n.smb && !n.nfs ? `No Samba or NFS on this machine yet: Shares on its ${pageLink("machine", "Features section")} installs them.`
    : !n.live ? "Its agent is not dialing in, so nothing from here reaches the machine." : "";
  const shares = n.shares || [];
  const rows = shares.map(s => `<div class="row stack2 stshare" data-share="${esc(s.name)}"><div class="grow">
      <div class="name">${esc(s.name)} <code>${esc(s.path)}</code></div>
      ${s.smb?.on ? `<div class="sub">SMB${s.smb.ro ? ", read-only" : ""}${s.smb.tm ? ", a Time Machine target" : ""}: ${s.smb.guest ? "everybody, as a guest" : (s.accounts || s.smb.users || []).map(esc).join(", ") || "nobody yet"} · \\\\${esc(n.name)}\\${esc(s.name)}</div>` : ""}
      ${s.nfs?.on ? `<div class="sub">NFS${s.nfs.ro ? ", read-only" : ""}: ${(s.nfs.clients || []).map(esc).join(", ")} · ${esc(n.name)}:${esc(s.path)}</div>` : ""}
      </div>${admin && !why ? `<span class="acts"><button type="button" class="danger" data-stshare="remove" data-name="${esc(s.name)}">Remove</button></span>` : ""}</div>`).join("");
  const mounts = (n.pools || []).map(p => p.mount).filter(Boolean);
  const form = !admin || why ? "" : `<div class="field stnewshare"><div class="hint">New share: a name, a folder on a pool${mounts.length ? ` (${mounts.map(esc).join(", ")})` : ""}, and who reaches it over SMB, NFS or both. A person reaches an SMB share with their account's name and the SMB password they set on Profile; a role names everybody holding it now.</div>
      <div class="field"><label class="pick"><span class="pickw">Name</span><input type="text" id="stShareName" placeholder="media" maxlength="63" autocomplete="off" spellcheck="false"></label></div>
      <div class="field"><label class="pick"><span class="pickw">Folder</span><input type="text" id="stSharePath" placeholder="${esc(mounts[0] ? mounts[0] + "/media" : "/mnt/tank/media")}" autocomplete="off" spellcheck="false"></label></div>
      <div class="field"><label class="ndcap"><input type="checkbox" id="stShareSmb" checked> SMB (Windows, a Mac, a phone)</label>
        <label class="ndcap"><input type="checkbox" id="stShareGuest"> everybody as a guest, no password</label>
        ${(n.accounts || []).length || (n.roles || []).length ? `<div class="lbox" id="stShareWho">${(n.roles || []).map(r => `<label class="ndcap"><input type="checkbox" data-stsharewho="role:${esc(r)}"> everybody with the role ${esc(r)}</label>`).join("")}${(n.accounts || []).map(a => `<label class="ndcap"><input type="checkbox" data-stsharewho="${esc(a)}"> ${esc(a)}</label>`).join("")}</div>` : ""}
        <label class="pick"><span class="pickw">Other users</span><input type="text" id="stShareUsers" placeholder="the machine's own users, separated by spaces" autocomplete="off" spellcheck="false"></label>
        <label class="ndcap"><input type="checkbox" id="stShareTm"> a Mac's Time Machine target</label></div>
      <div class="field"><label class="ndcap"><input type="checkbox" id="stShareNfs"> NFS (Linux, a hypervisor)</label>
        <label class="pick"><span class="pickw">Clients</span><input type="text" id="stShareClients" placeholder="192.168.1.0/24, or * for any" autocomplete="off" spellcheck="false"></label></div>
      <div class="field"><label class="ndcap"><input type="checkbox" id="stShareRo"> read-only</label></div>
      <div class="actbar"><span class="sp"></span><button type="button" class="primary" data-stshare="set">Share it</button></div></div>`;
  const body = `${why ? `<div class="sub dim">${esc(why)}</div>` : ""}${rows ? `<div class="rows">${rows}</div>` : `<div class="empty">No share yet${n.smb || n.nfs ? ": the form below makes one" : ""}.</div>`}${form}`;
  return docSection("storage", "shares", "Shares", shares.length ? String(shares.length) : "", body);
}
function wireStorageShares(root, n){
  root.querySelectorAll("[data-stshare]").forEach(b => b.onclick = () => pressing(b, async () => {
    const act = b.dataset.stshare, body = {action: "storage-share", id: n.node, share: act, name: b.dataset.name || ""};
    if (act === "set"){
      body.name = ($("stShareName")?.value || "").trim();
      body.path = ($("stSharePath")?.value || "").trim();
      const ro = !!$("stShareRo")?.checked;
      const who = [...root.querySelectorAll("[data-stsharewho]:checked")].map(i => i.dataset.stsharewho);
      body.smb = {on: !!$("stShareSmb")?.checked, guest: !!$("stShareGuest")?.checked, ro, tm: !!$("stShareTm")?.checked,
                  users: [...who, ...($("stShareUsers")?.value || "").split(/[\s,]+/).filter(Boolean)]};
      body.nfs = {on: !!$("stShareNfs")?.checked, ro, clients: ($("stShareClients")?.value || "").split(/[\s,]+/).filter(Boolean)};
      if (!body.name || !body.path){ notify("a share takes a name and a folder", true); return; }
    } else if (!await askYes(`Stop sharing ${body.name}? The folder and what is in it stay; nobody reaches it over SMB or NFS after.`, {title: "Remove the share?", verb: "Remove", danger: true})) return;
    busy(b, act === "set" ? "Sharing" : "Removing");
    const j = await (await postJSON("/api/v1/nodes", body)).json().catch(() => ({error: "no answer"}));
    notify(j.error || `${act === "set" ? "shared" : "removed"}: the job runs on the machine; the page follows its next check-in`, !!j.error);
    await refresh();
  }));
}

// The controller's own machine's ZFS pools (R162 step 1): each as zpool
// says it (size, used, health, the members by layout, the last scrub), with
// Scrub, Export and Destroy on its row; and New pool, a form that names the
// disks by model, size and serial before anything is written, every press
// a system job the root agent runs from its table.
function storagePools(n){
  if (!n.own) return "";
  const admin = !!state?.can?.admin && n.may_measure;
  const why = !n.zfs ? `No zpool on this machine yet: Storage on its ${pageLink("machine", "Features section")} installs it.`
    : !n.live ? "Its agent is not dialing in, so nothing from here reaches the machine." : "";
  const pools = n.pools || [];
  const free = (n.disks || []).filter(d => !d.system && !(d.parts || []).some(p => p.holds && p.holds !== "nothing") && (!d.holds || d.holds === "nothing"));
  const used = (n.disks || []).filter(d => !d.system && !free.includes(d));
  const diskLine = d => `${esc(d.name)}: ${esc(d.model || "unnamed")}, ${esc(humanBytes((d.size_mb || 0) * 1048576))}, serial ${esc(d.serial || "none")}`;
  const rows = pools.map(p => {
    const pct = p.size_mb ? (p.alloc_mb || 0) / p.size_mb * 100 : 0;
    const bad = !["online", ""].includes(p.health);
    return `<div class="row stack2 stpool${bad ? " bad" : ""}" data-pool="${esc(p.name)}"><div class="grow">
      <div class="name">${esc(p.name)} <span class="pill${bad ? " bad" : " ok"}">${esc(p.health || "unknown")}</span>${p.mount ? ` <span class="pill">${esc(p.mount)}</span>` : ""}</div>
      <div class="ndmeters">${meter("used", pct, `${sgb(p.alloc_mb)} / ${sgb(p.size_mb)}`, `${sgb(p.free_mb)} free`)}</div>
      ${(p.vdevs || []).map(v => `<div class="sub">${esc(v.type === "single" ? "disk" : v.type)}: ${v.disks.map(d => `<code>${esc(d.id.replace(/^\/dev\/disk\/by-id\//, ""))}</code>${d.state && d.state !== "online" ? ` <span class="pill bad">${esc(d.state)}</span>` : ""}`).join(", ")}</div>`).join("")}
      ${p.scrub ? `<div class="sub dim">${esc(p.scrub)}</div>` : ""}${p.errors && !/no known data errors/i.test(p.errors) ? `<div class="sub bad">${esc(p.errors)}</div>` : ""}
      </div>${admin && !why ? `<span class="acts"><button type="button" data-stpool="scrub" data-name="${esc(p.name)}">Scrub</button>${actMore([
        `<button type="button" data-stpool="export" data-name="${esc(p.name)}" title="unmount its datasets and let the disks go, to import elsewhere">Export</button>`,
        `<button type="button" class="danger" data-stpool="destroy" data-name="${esc(p.name)}" title="everything on it is gone">Destroy</button>`])}</span>` : ""}</div>`;
  }).join("");
  const form = !admin || why ? "" : `<div class="field stnewpool"><div class="hint">New pool: a name, a layout, and the disks it takes, each wiped. ${free.length ? `${free.length} disk${free.length === 1 ? "" : "s"} hold nothing` : "no disk here holds nothing"}${used.length ? `; ${used.length} hold something and take a tick to wipe` : ""}.</div>
      <div class="field"><label class="pick"><span class="pickw">Name</span><input type="text" id="stPoolName" placeholder="tank" maxlength="31" autocomplete="off" spellcheck="false"></label></div>
      <div class="field"><label class="pick"><span class="pickw">Layout</span><select id="stPoolLayout">
        <option value="mirror">mirror: two or more disks holding the same, one may fail</option>
        <option value="raidz2">raidz2: four or more disks, any two may fail</option>
        <option value="raidz1">raidz1: three or more disks, one may fail</option>
        <option value="single">single: one disk, nothing protects it</option></select></label></div>
      <div class="field"><div class="lbox" id="stPoolDisks">${[...free, ...used].map(d => `<label class="ndcap"><input type="checkbox" data-stdiskpick="${esc(d.name)}"${used.includes(d) ? ' data-held="1"' : ""}> ${diskLine(d)}${used.includes(d) ? ` <span class="pill warn">holds ${esc((d.parts || []).find(p => p.holds && p.holds !== "nothing")?.holds || d.holds)}</span>` : ""}</label>`).join("") || `<div class="empty">No disk to make a pool from.</div>`}</div></div>
      <div class="field"><label class="ndcap"><input type="checkbox" id="stPoolWipe"> wipe disks that hold something (what is on them is gone)</label></div>
      <div class="actbar"><span class="sp"></span><button type="button" class="primary" data-stpool="create">Make the pool</button></div></div>`;
  const body = `${why ? `<div class="sub dim">${esc(why)}</div>` : ""}${rows ? `<div class="rows">${rows}</div>` : `<div class="empty">No pool yet${n.zfs ? ": the form below makes one" : ""}.</div>`}${form}`;
  const sick = pools.filter(p => !["online", ""].includes(p.health)).length;
  return docSection("storage", "pools", "Pools", pools.length ? `${pools.length}${sick ? `, ${sick} not online` : ""}` : "", body, {cls: sick ? "bad" : ""});
}
function wireStoragePools(root, n){
  root.querySelectorAll("[data-stpool]").forEach(b => b.onclick = () => pressing(b, async () => {
    const act = b.dataset.stpool, body = {action: "storage-pool", id: n.node, pool: act, name: b.dataset.name || ""};
    if (act === "create"){
      body.name = ($("stPoolName")?.value || "").trim();
      body.layout = $("stPoolLayout")?.value || "mirror";
      body.disks = [...root.querySelectorAll("[data-stdiskpick]:checked")].map(i => i.dataset.stdiskpick);
      body.wipe = !!$("stPoolWipe")?.checked;
      if (!body.name || !body.disks.length){ notify("a pool takes a name and at least one disk", true); return; }
      const held = [...root.querySelectorAll("[data-stdiskpick]:checked[data-held]")].length;
      if (held && !body.wipe){ notify(`${held} of the disks picked hold something: tick wipe to take them`, true); return; }
      const names = body.disks.map(d => { const x = (n.disks || []).find(y => y.name === d); return x ? `${d} (${x.model || "unnamed"}, ${humanBytes((x.size_mb || 0) * 1048576)}, serial ${x.serial || "none"})` : d; });
      if (!await askYes(`Make the pool ${body.name} as a ${body.layout} of:\n\n${names.join("\n")}\n\nEverything on these disks is gone.`, {title: "Make the pool?", verb: "Make it", danger: true})) return;
    } else if (act === "destroy"){
      if (!await askYes(`Destroy the pool ${body.name}?\n\nEverything on it is gone; its disks hold nothing after.`, {title: "Destroy the pool?", verb: "Destroy it", danger: true})) return;
      body.confirm = body.name;
    } else if (act === "export"){
      if (!await askYes(`Export the pool ${body.name}? Its datasets are unmounted and the disks let go, to import elsewhere or here again.`, {title: "Export the pool?", verb: "Export"})) return;
    }
    busy(b, act === "scrub" ? "Scrubbing" : "Working");
    const j = await (await postJSON("/api/v1/nodes", body)).json().catch(() => ({error: "no answer"}));
    notify(j.error || `${act}: the job runs on the machine; the page follows its next check-in`, !!j.error);
    await refresh();
  }));
}

// Snapshots (R162 step 5): each pool's bb- snapshots as the census counts
// them, the pool's hourly, daily and weekly schedules (the Schedules
// page's rows, made here as system jobs on the machine), Snapshot now, and
// the newest ten with Roll back (the name typed again) and Delete.
const SNAP_KINDS = [["hourly", "Hourly", "0 * * * *"], ["daily", "Daily, at 4:00", "0 4 * * *"], ["weekly", "Weekly, Sundays at 4:00", "0 4 * * 0"]];
function storageSnapshots(n){
  if (!n.own) return "";
  const admin = !!state?.can?.admin && n.may_measure;
  const why = !n.zfs ? `No zfs on this machine yet: Storage on its ${pageLink("machine", "Features section")} installs it.`
    : !n.live ? "Its agent is not dialing in, so nothing from here reaches the machine." : "";
  const pools = n.pools || [], snaps = n.snapshots || {}, scheds = n.snapshot_schedules || [];
  const when = at => at ? new Date(at * 1000).toLocaleString() : "";
  const rows = pools.map(p => {
    const v = snaps[p.name] || {count: 0, used_mb: 0, kinds: {}, newest: []};
    const mine = scheds.filter(x => x.pool === p.name);
    const kinds = SNAP_KINDS.map(([k, label]) => {
      const sch = mine.find(x => x.kind === k);
      return `<span class="pill${sch?.on ? " ok" : ""}" data-snapkind="${k}">${esc(label.split(",")[0].toLowerCase())}: ${sch ? `${sch.keep} kept${sch.on ? "" : ", off"}` : "none"}</span>`;
    }).join(" ");
    const newest = (v.newest || []).map(x => `<div class="row stsnap" data-snap="${esc(x.name)}"><div class="grow"><code>${esc(x.name)}</code> <span class="dim">${esc(when(x.at))}</span></div>${
      admin && !why ? `<span class="acts">${actMore([
        `<button type="button" data-stsnap="rollback" data-pool="${esc(p.name)}" data-name="${esc(x.name)}" title="the pool as it was then; everything since is gone">Roll back</button>`,
        `<button type="button" class="danger" data-stsnap="destroy" data-pool="${esc(p.name)}" data-name="${esc(x.name)}">Delete</button>`], true)}</span>` : ""}</div>`).join("");
    return `<div class="row stack2 stpoolsnaps" data-pool="${esc(p.name)}"><div class="grow">
      <div class="name">${esc(p.name)} <span class="pill">${v.count} snapshot${v.count === 1 ? "" : "s"}${v.used_mb ? `, ${esc(humanBytes(v.used_mb * 1048576))}` : ""}</span></div>
      <div class="sub">${kinds}</div>
      ${newest ? `<div class="rows">${newest}</div>` : `<div class="empty">No snapshot of ${esc(p.name)} yet.</div>`}
      </div>${admin && !why ? `<span class="acts"><button type="button" data-stsnap="take" data-pool="${esc(p.name)}" title="one of every dataset, kept beside the manual ones">Snapshot now</button></span>` : ""}</div>`;
  }).join("");
  const form = !admin || why || !pools.length ? "" : `<div class="field stsnapform"><div class="hint">A schedule: the pool, how often, and how many of that kind to keep; the oldest past that goes when the next is taken.</div>
      <div class="prefrow ctlrow">
        <div class="setrow col ctlrow"><label class="pick"><span class="pickw">Pool</span><select id="stSnapPool">${optionList(pools.map(p => [p.name, p.name]), pools[0].name)}</select></label></div>
        <div class="setrow col ctlrow"><label class="pick"><span class="pickw">How often</span><select id="stSnapKind">${optionList(SNAP_KINDS.map(([k, label]) => [k, label]), "daily")}</select></label></div>
        <div class="setrow col ctlrow"><label class="pick"><span class="pickw">Keep</span><input type="number" id="stSnapKeep" min="1" max="200" value="7"></label></div>
      </div>
      <div class="actbar"><span class="sp"></span>${scheds.length ? actMore(scheds.map(x => `<button type="button" class="danger" data-stsnapsched="${esc(x.id)}">Remove ${esc(x.pool)} ${esc(x.kind)}</button>`), true) : ""}<button type="button" class="primary" data-stsnap="schedule">Save the schedule</button></div></div>`;
  const body = `${why ? `<div class="sub dim">${esc(why)}</div>` : ""}${rows ? `<div class="rows">${rows}</div>` : `<div class="empty">No pool yet: snapshots are a pool's.</div>`}${form}`;
  const total = pools.reduce((a, p) => a + ((snaps[p.name] || {}).count || 0), 0);
  return docSection("storage", "snapshots", "Snapshots", pools.length ? `${total}${scheds.length ? `, ${scheds.filter(x => x.on).length} scheduled` : ""}` : "", body);
}
function wireStorageSnapshots(root, n){
  root.querySelectorAll("[data-stsnap]").forEach(b => b.onclick = () => pressing(b, async () => {
    const act = b.dataset.stsnap;
    if (act === "schedule"){
      const pool = $("stSnapPool")?.value || "", kind = $("stSnapKind")?.value || "daily", keep = parseInt($("stSnapKeep")?.value || "0", 10);
      if (!pool || !(keep >= 1 && keep <= 200)){ notify("a schedule takes a pool and keeps 1 to 200 snapshots", true); return; }
      const was = (n.snapshot_schedules || []).find(x => x.pool === pool && x.kind === kind);
      const body = {action: "save", ...(was ? {id: was.id} : {}), name: `Snapshots of ${pool}, ${kind}`, cron: SNAP_KINDS.find(k => k[0] === kind)[2],
                    node: n.node, on: true, system: {apply: "storage-snapshot", config: {pool, kind, keep}}};
      busy(b, "Saving");
      const j = await (await postJSON("/api/schedules", body)).json().catch(() => ({error: "no answer"}));
      notify(j.error || `${pool}: ${kind} snapshots, ${keep} kept (${j.schedule?.words || ""}); the row is on the Schedules page too`, !!j.error);
      await refresh();
      return;
    }
    const body = {action: "storage-snapshot", id: n.node, snapshot: act, pool: b.dataset.pool || "", name: b.dataset.name || "", dataset: b.dataset.pool || ""};
    if (act === "rollback"){
      const typed = await askText(`Roll ${body.pool} back to ${body.name}?\n\nEverything written to the pool since then is gone, and every snapshot since it with it.`, {verb: "Roll back", label: "The snapshot's name, typed again"});
      if (typed === null || typed === undefined) return;
      if (String(typed).trim() !== body.name){ notify("the name typed is not the snapshot's; nothing rolled back", true); return; }
      body.confirm = body.name;
    } else if (act === "destroy"){
      if (!await askYes(`Delete the snapshot ${body.name} of ${body.pool}?`, {title: "Delete the snapshot?", verb: "Delete it", danger: true})) return;
    } else {
      body.kind = "manual"; body.keep = 50;
    }
    busy(b, act === "take" ? "Taking" : "Working");
    const j = await (await postJSON("/api/v1/nodes", body)).json().catch(() => ({error: "no answer"}));
    notify(j.error || `${act}: the job runs on the machine; the page follows its next check-in`, !!j.error);
    await refresh();
  }));
  root.querySelectorAll("[data-stsnapsched]").forEach(b => b.onclick = () => pressing(b, async () => {
    const x = (n.snapshot_schedules || []).find(y => y.id === b.dataset.stsnapsched);
    if (!await askYes(`Remove the ${x?.kind || ""} schedule of ${x?.pool || "the pool"}? The snapshots it took stay.`, {title: "Remove the schedule?", verb: "Remove"})) return;
    const j = await (await postJSON("/api/schedules", {action: "remove", id: b.dataset.stsnapsched})).json().catch(() => ({error: "no answer"}));
    notify(j.error || "the schedule is gone", !!j.error);
    await refresh();
  }));
}

// The array (R162 step 2): disks of mixed sizes each their own filesystem,
// one tree over them by mergerfs, parity on one or two disks kept by
// SnapRAID on a schedule (not in real time: what was written since the last
// sync is unprotected until the next, said on the section). Each disk by
// slot with its room, Sync now, Scrub and Check, a disk added or a slot's
// disk replaced, the sync and scrub schedules (the Schedules page's rows),
// and a form for a new array that names the disks by model, size and
// serial and says the whole again before anything is written.
const ARRAY_POLICIES = [["mfs", "most free space: each new file lands on the emptiest disk"], ["epmfs", "existing path first, then most free space: a folder's files stay together"],
                        ["lfs", "fill up: one disk fills before the next is used"], ["ff", "the first disk with room"]];
const ARRAY_KINDS = [["sync", "Sync", "0 4 * * *", "Daily, at 4:00"], ["scrub", "Scrub", "0 5 * * 0", "Weekly, Sundays at 5:00"]];
function storageArray(n){
  if (!n.own) return "";
  const admin = !!state?.can?.admin && n.may_measure;
  const why = !n.mergerfs || !n.snapraid ? `No mergerfs or SnapRAID on this machine yet: Storage on its ${pageLink("machine", "Features section")} installs them.`
    : !n.live ? "Its agent is not dialing in, so nothing from here reaches the machine." : "";
  const a = n.array || {}, has = (a.data || []).length > 0, scheds = (n.snapshot_schedules || []).filter(x => x.array);
  const free = (n.disks || []).filter(d => !d.system && !(d.parts || []).some(p => p.holds && p.holds !== "nothing") && (!d.holds || d.holds === "nothing"));
  const used = (n.disks || []).filter(d => !d.system && !free.includes(d) && !(d.parts || []).some(p => /^(xfs|btrfs) at \/mnt\/(disks|parity)\//.test(p.holds || "")) && !/^(xfs|btrfs) at \/mnt\/(disks|parity)\//.test(d.holds || ""));
  const diskLine = d => `${esc(d.name)}: ${esc(d.model || "unnamed")}, ${esc(humanBytes((d.size_mb || 0) * 1048576))}, serial ${esc(d.serial || "none")}`;
  const when = t => t ? ago(t) : "never";
  const slotRow = (kind, x) => {
    const pct = x.size_mb ? (x.used_mb || 0) / x.size_mb * 100 : 0;
    return `<div class="row stslot${x.mounted ? "" : " bad"}" data-slot="${kind}${x.slot}"><div class="grow">
      <div class="name">${kind}${x.slot} <span class="pill">${kind === "d" ? "data" : "parity"}</span>${x.mounted ? "" : ` <span class="pill bad">not mounted</span>`} <code>${esc(x.id.replace(/^\/dev\/disk\/by-id\//, ""))}</code></div>
      ${x.mounted ? `<div class="ndmeters">${meter("used", pct, `${sgb(x.used_mb)} / ${sgb(x.size_mb)}`, `${sgb((x.size_mb || 0) - (x.used_mb || 0))} free`)}</div>` : ""}
      </div>${admin && !why && free.length ? `<span class="acts">${actMore([`<button type="button" data-starray="replace" data-which="${kind}${x.slot}" title="a new disk takes this slot; ${kind === "d" ? "its files are rebuilt from parity" : "parity is rebuilt on it"}">Replace</button>`], true)}</span>` : ""}</div>`;
  };
  const pick = (id, held) => `<div class="field"><div class="lbox" id="${id}">${[...free, ...(held ? used : [])].map(d => `<label class="ndcap"><input type="checkbox" data-${id}="${esc(d.name)}"${used.includes(d) ? ' data-held="1"' : ""}> ${diskLine(d)}${used.includes(d) ? ` <span class="pill warn">holds ${esc((d.parts || []).find(p => p.holds && p.holds !== "nothing")?.holds || d.holds)}</span>` : ""}</label>`).join("") || `<div class="empty">No disk free for it.</div>`}</div></div>`;
  let body;
  if (has){
    const kinds = ARRAY_KINDS.map(([k, label]) => { const sch = scheds.find(x => x.array === k); return `<span class="pill${sch?.on ? " ok" : ""}">${label.toLowerCase()}: ${sch ? `${esc(sch.words || "")}${sch.on ? "" : ", off"}` : "not scheduled"}</span>`; }).join(" ");
    const total = (a.data || []).reduce((s, x) => s + (x.size_mb || 0), 0), usedT = (a.data || []).reduce((s, x) => s + (x.used_mb || 0), 0);
    body = `<div class="row stack2"><div class="grow">
        <div class="name">${esc(a.mount || "/mnt/array")} <span class="pill${a.mounted ? " ok" : " bad"}">${a.mounted ? "mounted" : "not mounted"}</span>${a.running ? ` <span class="pill warn">${esc(a.running)} running</span>` : ""}</div>
        <div class="ndmeters">${meter("used", total ? usedT / total * 100 : 0, `${sgb(usedT)} / ${sgb(total)}`, `${(a.data || []).length} data, ${(a.parity || []).length} parity`)}</div>
        ${factGrid([["Last sync", when(a.last_sync)], ["Last scrub", when(a.last_scrub)], ["Last check", when(a.last_check)], ["New files land on", (ARRAY_POLICIES.find(p => p[0] === a.policy) || [a.policy, a.policy])[1]]])}
        <div class="sub">${kinds}</div>
        ${a.status ? `<div class="sub dim">${esc(a.status)}</div>` : ""}
        <div class="hint">Parity is periodic: what was written since the last sync is not protected until the next one runs.</div>
      </div>${admin && !why ? `<span class="acts"><button type="button" data-starray="sync" title="bring the parity up to date now">Sync now</button>${actMore([
        `<button type="button" data-starray="scrub" title="read a part of the array back against its parity">Scrub</button>`,
        `<button type="button" data-starray="check" title="SnapRAID's status: what is out of date and what it found">Check</button>`,
        `<button type="button" class="danger" data-starray="destroy" title="unmounted and forgotten; the disks keep their files">Destroy</button>`])}</span>` : ""}</div>
      <div class="rows">${(a.data || []).map(x => slotRow("d", x)).join("")}${(a.parity || []).map(x => slotRow("p", x)).join("")}</div>
      ${admin && !why ? `<div class="field stnewslot"><div class="hint">Add a data disk: it is wiped, takes the next slot, and the parity is synced after${free.length ? "" : "; no disk here is free"}.</div>
        ${pick("stArrayAdd", true)}
        <div class="field"><label class="ndcap"><input type="checkbox" id="stArrayWipe2"> wipe disks that hold something (what is on them is gone)</label></div>
        <div class="actbar"><span class="sp"></span><button type="button" data-starray="add">Add the disk</button></div></div>
      <div class="field"><div class="hint">A schedule: the parity synced daily and a scrub weekly is the usual pair.</div>
        <div class="prefrow ctlrow">
          <div class="setrow col ctlrow"><label class="pick"><span class="pickw">Run</span><select id="stArraySched">${optionList(ARRAY_KINDS.map(([k, label, , said]) => [k, `${label}, ${said.toLowerCase()}`]), "sync")}</select></label></div>
        </div>
        <div class="actbar"><span class="sp"></span>${scheds.length ? actMore(scheds.map(x => `<button type="button" class="danger" data-stsnapsched="${esc(x.id)}">Remove the ${esc(x.array)} schedule</button>`), true) : ""}<button type="button" class="primary" data-starray="schedule">Save the schedule</button></div></div>` : ""}`;
  } else {
    const form = !admin || why ? "" : `<div class="field stnewarray"><div class="hint">New array: the data disks (any sizes, each wiped and given its own filesystem), one or two parity disks at least as large as the largest data disk, and where new files land.</div>
      <div class="field"><div class="hint">Data disks</div>${pick("stArrayData", true)}</div>
      <div class="field"><div class="hint">Parity disks</div>${pick("stArrayParity", true)}</div>
      <div class="prefrow ctlrow">
        <div class="setrow col ctlrow"><label class="pick"><span class="pickw">Filesystem</span><select id="stArrayFs"><option value="xfs">xfs: the usual choice</option><option value="btrfs">btrfs: checksums per file</option></select></label></div>
        <div class="setrow col ctlrow"><label class="pick"><span class="pickw">New files land on</span><select id="stArrayPolicy">${optionList(ARRAY_POLICIES, "mfs")}</select></label></div>
      </div>
      <div class="field"><label class="ndcap"><input type="checkbox" id="stArrayWipe"> wipe disks that hold something (what is on them is gone)</label></div>
      <div class="actbar"><span class="sp"></span><button type="button" class="primary" data-starray="create">Make the array</button></div></div>`;
    body = `<div class="empty">No array yet${n.mergerfs && n.snapraid ? ": the form below makes one" : ""}.</div>${form}`;
  }
  return docSection("storage", "array", "Array", has ? `${(a.data || []).length} data, ${(a.parity || []).length} parity` : "", `${why ? `<div class="sub dim">${esc(why)}</div>` : ""}${body}`,
                    {cls: has && (!a.mounted || (a.data || []).some(x => !x.mounted)) ? "bad" : ""});
}
function wireStorageArray(root, n){
  const picked = id => [...root.querySelectorAll(`[data-${id}]:checked`)].map(i => i.getAttribute(`data-${id}`));
  const heldAmong = id => [...root.querySelectorAll(`[data-${id}]:checked[data-held]`)].length;
  const say = names => names.map(d => { const x = (n.disks || []).find(y => y.name === d); return x ? `${d} (${x.model || "unnamed"}, ${humanBytes((x.size_mb || 0) * 1048576)}, serial ${x.serial || "none"})` : d; });
  root.querySelectorAll("[data-starray]").forEach(b => b.onclick = () => pressing(b, async () => {
    const act = b.dataset.starray;
    if (act === "schedule"){
      const kind = $("stArraySched")?.value || "sync", k = ARRAY_KINDS.find(x => x[0] === kind);
      const was = (n.snapshot_schedules || []).find(x => x.array === kind);
      const body = {action: "save", ...(was ? {id: was.id} : {}), name: `Array ${kind}`, cron: k[2], node: n.node, on: true, system: {apply: "storage-array", config: {array: kind}}};
      busy(b, "Saving");
      const j = await (await postJSON("/api/schedules", body)).json().catch(() => ({error: "no answer"}));
      notify(j.error || `the array's ${kind}: ${j.schedule?.words || ""}; the row is on the Schedules page too`, !!j.error);
      await refresh();
      return;
    }
    const body = {action: "storage-array", id: n.node, array: act};
    if (act === "create"){
      body.data = picked("stArrayData"); body.parity = picked("stArrayParity");
      body.fs = $("stArrayFs")?.value || "xfs"; body.policy = $("stArrayPolicy")?.value || "mfs"; body.wipe = !!$("stArrayWipe")?.checked;
      if (!body.data.length || !body.parity.length){ notify("an array takes at least one data disk and one parity disk", true); return; }
      if (body.data.some(d => body.parity.includes(d))){ notify("a disk is data or parity, not both", true); return; }
      const held = heldAmong("stArrayData") + heldAmong("stArrayParity");
      if (held && !body.wipe){ notify(`${held} of the disks picked hold something: tick wipe to take them`, true); return; }
      if (!await askYes(`Make the array?\n\nData, each ${body.fs}:\n${say(body.data).join("\n")}\n\nParity:\n${say(body.parity).join("\n")}\n\nEverything on these disks is gone. Parity is kept by SnapRAID on a schedule, not in real time.`, {title: "Make the array?", verb: "Make it", danger: true})) return;
    } else if (act === "add"){
      body.disk = picked("stArrayAdd")[0] || ""; body.wipe = !!$("stArrayWipe2")?.checked;
      if (!body.disk){ notify("pick the disk to add", true); return; }
      if (heldAmong("stArrayAdd") && !body.wipe){ notify("the disk picked holds something: tick wipe to take it", true); return; }
      if (!await askYes(`Add ${say([body.disk])[0]} to the array as its next data disk? Everything on it is gone, and the parity is synced after.`, {title: "Add the disk?", verb: "Add it", danger: true})) return;
    } else if (act === "replace"){
      body.which = b.dataset.which;
      const free = (n.disks || []).filter(d => !d.system && !(d.parts || []).some(p => p.holds && p.holds !== "nothing") && (!d.holds || d.holds === "nothing"));
      const choice = await ask({title: `Replace ${body.which}`, text: `The disk that takes the slot ${body.which}; it is wiped, then ${body.which[0] === "d" ? "its files are rebuilt from parity" : "the parity is rebuilt on it"}, which takes hours.`,
                                choices: free.map(d => ({label: say([d.name])[0], value: d.name}))});
      if (!choice) return;
      body.new = choice;
    } else if (act === "destroy"){
      const typed = await askText("Destroy the array?\n\nIt is unmounted and forgotten; every data disk keeps its files, readable on any Linux, and the parity disks are left as they are.", {verb: "Destroy", label: "Type array to go on"});
      if (typed === null || typed === undefined) return;
      if (String(typed).trim() !== "array"){ notify("the word typed is not array; nothing destroyed", true); return; }
      body.confirm = "array";
    }
    busy(b, {sync: "Syncing", scrub: "Scrubbing", check: "Checking"}[act] || "Working");
    const j = await (await postJSON("/api/v1/nodes", body)).json().catch(() => ({error: "no answer"}));
    notify(j.error || `${act}: the job runs on the machine; its log is on the Jobs page and the page follows the next check-in`, !!j.error);
    await refresh();
  }));
}

function storageProjects(n, where){
  const rows = [...(n.projects || [])];
  if (n.other) rows.push({name: "other projects", other: true, ...n.other});
  if (!rows.length) return `<div class="empty">no project's folders here yet</div>`;
  // The ones holding nothing here are one line, not a row of "none" each
  // (R203): four of five read none / 0 MB on a node that held one project.
  const empty = rows.filter(r => !r.other && !r.total);
  const shown = rows.filter(r => r.other || r.total);
  const cols = where.filter(w => shown.some(r => r[w]));
  // A table (R218 step 27, the tables rule): a head naming the columns at a
  // desk, and on a phone each cell its column's word beside its number,
  // since a column of bare numbers under a name said nothing (B655). An
  // empty cell says so.
  const tcols = [{label: "Project"}, ...cols.map(w => ({label: w, num: true})), {label: "total", num: true}];
  const tail = empty.length ? `<div class="field stnone"><div class="sub">${esc(andList(empty.map(r => projLabel(r.name))))} hold${empty.length === 1 ? "s" : ""} nothing here</div></div>` : "";
  if (!shown.length) return tail;
  return tblWrap(tcols, shown.map(r => `<div class="row stack2 stproj${r.other ? " dim" : ""}">${tblLine(tcols, [
      `<span class="name">${r.other ? "other projects <span class=\"dim\">· ones you cannot see</span>" : esc(projLabel(r.name))}</span>`,
      ...cols.map(w => r[w] ? sgb(r[w]) : `<span class="dim">none</span>`), `<b>${sgb(r.total)}</b>`])}</div>`).join(""), "sttbl") + tail;
}

// Each project's virtual phones on the node (R123 step 1), largest first,
// whoever's they are among the projects this account sees: measured here,
// removed on the Emulator page, the page that manages them (the operator,
// 23 Oct).
function storagePhones(n){
  const rows = [...(n.phones || [])].sort((a, b) => (b.mb || 0) - (a.mb || 0));
  const cols = [{label: "Phone"}, {label: "Project"}, {label: "Account"}, {label: "last started"},
                {label: "snapshot", num: true}, {label: "size", num: true}];
  return `<div class="field"><div class="hint">Each is removed on the ${pageLink("emulator", "Emulator page")}, with this node picked.</div></div>`
    + tblWrap(cols, rows.map(p => `<div class="row stack2 stphone">${tblLine(cols, [
      `<span class="name">${esc(p.name)}</span>${p.running ? ` <span class="pill ok">running</span>` : ""}`,
      esc(projLabel(p.project)), `<span class="dim">${esc(p.uid === state?.uid ? "yours" : p.uid || "the session account")}</span>`,
      p.running ? "now" : p.ran ? esc(ago(p.ran)) : `<span class="dim">never</span>`,
      p.snap_mb ? sgb(p.snap_mb) : `<span class="dim">none</span>`,
      p.mb === null || p.mb === undefined ? `<span class="dim">?</span>` : sgb(p.mb)])}</div>`).join(""), "sttbl");
}

// Measure now, the page's upkeep, in its bar with every header button (the
// operator, 17 Oct): the walk's numbers arrive with the node's census, which
// the page follows, so it has no Refresh.
// Given GHOST, the placeholder's: there and dead until the node is known.
function storageMeasureBtn(n){
  if (n === GHOST) return storageMay ? `<button type="button" disabled>Measure now</button>` : "";
  if (!n || !storageMay || n.may_measure === false) return "";
  return `<button type="button" data-stmeasure="${esc(n.node)}" ${n.live ? "" : "disabled"} title="${
    n.live ? "walk the disks now; the next report brings the numbers" : "the node is not dialing in"}">Measure now</button>`;
}
// The bar: the node and Measure now; given nothing, the placeholder's.
function storageBar(pnodes, n){
  return nodeBar(nodePick("stNodeSel", pnodes, storageNode), storageMeasureBtn(pnodes ? n : GHOST));
}

// What the tab says about one node: the state row, then its disks. Given
// null, the placeholder (R218, the operator 18 Oct: drawn by the page's own
// code so it cannot drift): the same bands and By project, shimmering where
// the node's numbers go.
function storageBody(n, where){
  // Where its stores are set, a fact of the head's (the operator, 25 Oct:
  // no loose words at a page's top).
  const setOn = [["Stores set on", `its row on the ${pageLink("nodes", "Nodes page")}`, {html: true}]];
  const byProject = (count, body) => docSection("storage", "projects", "By project", count,
    `<div class="field"><div class="hint">What each project's folders hold${n ? ` on ${esc(n.name)}` : ""}.${helpIcon("Its synced copy, build cache, artifacts, dev instance data, emulators and the accounts' build caches.")}</div></div>
      ${body}`);
  if (!n) return `${pageHead({title: GHOST, cls: "toolstate", facts: [["Measured", GHOST], ["Walk", GHOST], ...setOn]})}${skRows(2)}${byProject("", skRows(3))}`;
  const age = !n.measured ? "not measured yet"
    : n.age_s < 3600 ? `measured ${Math.round(n.age_s / 60)} min ago` : `measured ${Math.round(n.age_s / 3600)} h ago`;
  const pill = `<span class="pill${n.measured ? "" : " warn"}">${esc(age)}</span>`;
  // The walk as a head's facts (R218 step 27; the operator, 25 Oct), and
  // the memory BuilderBot's work is kept to there (R110 step 4).
  const fence = !("fence" in n) ? "" : n.fence ? `${humanBytes(n.fence[0] * 1048576)}, ${humanBytes(n.fence[1] * 1048576)} in use`
    : "not fenced from the system's memory: run its setup again";
  const head = pageHead({title: n.name || "", pills: pill, cls: "toolstate", facts: [
    ["Walk", n.measured ? `${n.took_s ? `took ${n.took_s}s, ` : ""}every hour` : "an hour after the agent starts, then every hour"],
    ["Its work's memory", fence], ...setOn]});
  return `<div data-stnode="${esc(n.node)}">
    ${head}
    ${storageMachineDisks(n)}
    ${storagePools(n)}
    ${storageArray(n)}
    ${storageSnapshots(n)}
    ${storageShares(n)}
    ${storageDisks(n)}
    ${byProject(`${(n.projects || []).length} project${(n.projects || []).length === 1 ? "" : "s"}`, storageProjects(n, where))}
    ${(n.phones || []).length ? docSection("storage", "phones", "Phones", `${n.phones.length}, ${sgb(n.phones.reduce((a, p) => a + (p.mb || 0), 0))}`, storagePhones(n)) : ""}
    ${n.slow?.length ? `<div class="field"><div class="hint warn">Not measured in time: ${esc(n.slow.join(", "))}. A slow share; the next walk tries again.</div></div>` : ""}
  </div>`;
}

function renderStorageInto(i){
  const d = docSurface(i, "storage");
  if (!d) return;
  if (storageList === null){
    // The page's own bar and body, given nothing.
    d.setBar(storageBar(null));
    d.list.innerHTML = skTpl(storageBody(null));
    loadStorage();
    return;
  }
  if (storageErr){
    d.list.innerHTML = `<div class="hint bad">${esc(storageErr)}</div>`;
    return;
  }
  const where = ["workspace", "cache", "artifacts", "appdata", "emulator", "builds"];
  const n = storagePick();
  const pnodes = storageList.map(x => ({id: x.node, name: x.name, live: x.live}));
  // One order for every page's top (the operator, 17 Oct): the node and
  // Measure now in the bar; when it was measured on the status line under it.
  d.setBar(storageBar(pnodes, n));
  d.list.innerHTML = n ? storageBody(n, where)
    : noNodeYet("the disks measured here are a node's");
  wireStorageTab(d.el);
  if (n) wireStorageShares(d.el, n);
  if (n) wireStoragePools(d.el, n);
  if (n) wireStorageSnapshots(d.el, n);
  if (n) wireStorageArray(d.el, n);
}

function wireStorageTab(root){
  // Its sections fold as every page's do: one open at a time on a phone,
  // sliding, where they snapped and stood open together (B171).
  wireSections(root);
  const psel = root.querySelector("#stNodeSel");
  // A pick is a history entry (B31), so Back returns to the node before.
  if (psel) psel.onchange = () => navPush(() => { storageNode = psel.value;
                                    try{ localStorage.setItem("bb.stnode", storageNode); }catch(e){ /* private */ }
                                    storageRev++; drawPanes(); });
  root.querySelectorAll("[data-stdisk]").forEach(c => c.onclick = () => {
    storageDisk = c.dataset.stdisk; storageRev++; drawPanes();
  });
  root.querySelectorAll("[data-stprune]").forEach(a => a.onclick = e => {
    e.preventDefault();
    sectOpen["docker:images"] = true;
    openDockerOn(a.dataset.stprune);
  });
  root.querySelectorAll("[data-stmeasure]").forEach(b => b.onclick = async () => {
    busy(b, "Asking");
    const j = await (await postJSON("/api/storage", {action: "measure", node: b.dataset.stmeasure})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else notify("measuring: the numbers arrive with the node's next report, in a minute or so");
    await loadStorage();
  });
}
