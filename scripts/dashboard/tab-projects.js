// The Projects tab and the bin behind it: every project as a row with its
// controls, and what Unlink and Delete left to purge.
// One classic script beside index.html (docs/design-language.md, Files): pure
// declarations, nothing runs at load.

"use strict";

async function postTrash(path, body){
  try{
    const r = await postJSON(path, body);
    return await r.json();
  }catch(e){ return {error: String(e)}; }
}

async function openTrash(){
  $("tmodal").hidden = false;
  await drawTrash();
}

async function drawTrash(){
  const el = $("tList");
  el.innerHTML = `${skel("rows", 3)}`;
  let j;
  try{ j = await (await fetch("/api/trash")).json(); }
  catch(e){ el.innerHTML = `<div class="hint bad">${esc(String(e))}</div>`; return; }
  // A refusal is said, never read as an empty bin (B87).
  if (j?.error){ el.innerHTML = `<div class="hint bad">${esc(j.error)}</div>`; return; }
  const items = j?.items || [];
  if (!items.length){
    el.innerHTML = `<div class="empty">nothing deleted</div>`;
    return;
  }
  el.innerHTML = items.map(t => `<div class="row trow" data-t="${esc(t.name)}">
      <div class="grow"><div class="name">${esc(t.was || t.name)}</div>
        <div class="sub">deleted ${esc(ago(t.at))}${t.project ? ` from ${esc(t.project)}` : ""}${t.was && t.was !== t.name
          ? ` · directory ${esc(t.name)}` : ""}${t.taken
          ? ` · <span class="warn">its directory is in use again</span>` : ""}</div></div>
      <span class="acts">
        <button type="button" data-trestore="${esc(t.name)}"${t.taken ? " disabled" : ""}
          title="${t.taken
            ? "a directory of that name is back under /workspace: move it first"
            : "move it back to /workspace, as " + esc(t.was || t.name)}">Put back</button>
        <button type="button" class="ic danger" data-tpurge="${esc(t.name)}" aria-label="delete for good"
          title="delete it and every file in it, for good">${BIN}</button>
      </span></div>`).join("");
  el.querySelectorAll("[data-trestore]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    let r = await postTrash("/api/trash-restore", {name: b.dataset.trestore});
    // Its project is gone (R138): which one it goes back into is asked.
    if (r?.pick){
      const to = projectList().filter(c => c.may && !c.archived);
      const got = to.length ? await askInline(b.closest(".trow"), {label: `Put ${b.dataset.trestore} back into`, ok: "Put back",
                                                                   options: to.map(c => c.name)}) : null;
      const c = got && to.find(x => x.name.toLowerCase() === got.toLowerCase());
      if (!c){ if (!to.length) notify(r.error, true); b.disabled = false; return; }
      r = await postTrash("/api/trash-restore", {name: b.dataset.trestore, project: c.key});
    }
    if (r?.error) notify(r.error, true);
    else notify(`${r.label || r.name} is back`);
    await drawTrash(); refresh();
  });
  el.querySelectorAll("[data-tpurge]").forEach(b => b.onclick = () => askPurge(b.dataset.tpurge));
}

// Typed, not clicked. There is nothing after this one: no .trash to fish it
// out of a second time, and the ceremony is the difference between a control
// somebody meant to press and one their thumb found.
function askPurge(name){
  const row = $("tList").querySelector(`.trow[data-t="${CSS.escape(name)}"]`);
  if (!row || row.querySelector(".dropbox")) return;
  const box = document.createElement("div");
  box.className = "dropbox ctlown";
  // The type-to-confirm shape Reset BuilderBot has: what goes, then the
  // word to type labeled over its field, then the drop box's Keep it and
  // the red verb.
  box.innerHTML = `<div class="hint bad">This deletes every file in
      <b>${esc(name)}</b>. It is not moved anywhere and there is nothing to
      undo it with.</div>
    <label class="lbl" for="purgeWord">Type ${esc(name)} to confirm</label>
    <input id="purgeWord" autocomplete="off" placeholder="${esc(name)}">
    <div class="foot"><span class="sp"></span>
      <button type="button" class="stop">Keep it</button>
      <button type="button" class="danger" disabled>Delete for good</button></div>`;
  row.appendChild(box);
  const input = box.querySelector("input"), go = box.querySelector(".danger");
  input.oninput = () => { go.disabled = input.value.trim() !== name; };
  input.focus();
  box.querySelector(".stop").onclick = () => box.remove();
  go.onclick = async () => {
    go.disabled = true;
    const r = await postTrash("/api/trash-purge", {name, confirm: input.value.trim()});
    if (r?.error){ notify(r.error, true); go.disabled = false; return; }
    notify(`${name} is gone`);
    await drawTrash();
  };
}

const BIN = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M2.8 4.3h10.4"/><path d="M6.4 4.3V2.9h3.2v1.4"/>
  <path d="M4.2 4.3l.7 8.3a1 1 0 0 0 1 .9h4.2a1 1 0 0 0 1-.9l.7-8.3"/>
  <path d="M6.8 6.8v4"/><path d="M9.2 6.8v4"/></svg>`;

// Every project, and the whole of each one. Home is a view of this filtered
// to what is pinned, so a project that is not on Home has lost nothing but
// its place there, which is the only promise a pin makes.
function openProjectsTab(){
  openTab({kind: "projects", arg: "__projects", label: "Projects"});
}

// What the search box narrows the grid to: a view, this browser's, never
// saved. Matched against a project's name and each of its repositories'
// names, branches and nodes.
let pjQuery = "";
// The group chip in force, "" for All and "none" for the projects in no
// group: a view for the page's life, as the Containers page's chips are.
let pjChip = "";
function projectMatches(p, q){
  if (!q) return true;
  const hay = [p, ...(p.rows || [])].flatMap(x => [x.name, x.label, x.git, x.node_name, x.session_at])
    .filter(Boolean).join(" ").toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every(w => hay.includes(w));
}

// One project's card on the grid (R218 step 3): its color down the left
// edge, the name (a press opens its page), the branch and the node, the
// session's dot and word, the one notice, and the two actions with the
// rest behind the menu, the same parts the project page's header draws.
// A project's lock, said one way on its card, its page's header and Home
// (consistency batch J: the header said locked where the card said
// archived): locked when its owner or an administrator locked it (R119),
// whomever it holds out, read-only when it is not this account's to change
// (not taken on, or a role that reads it alone). Archived is said by where
// the card sits, not by a mark.
function lockMark(p){
  const said = p.locked ? (p.locked_admin ? "locked by an administrator" : "locked") : writeWhy(p) ? "read-only" : "";
  return said ? ` <span class="lockmark" title="${esc(p.locked ? lockedWhy(p) : said)}">${LOCK}${said}</span>` : "";
}
// A project's facts line, the same parts wherever it is drawn: its id, its
// branch, that it may push, and the node it runs on.
function projFacts(p){
  const node = p.node_name || p.session_at || "";
  return [p.pid ? `<span class="pid" title="this project's id, which never changes: bb -p ${projId(p)} names it">${projId(p)}</span>` : "",
          p.git ? `git: <span class="pbr">${esc(p.git)}</span>${p.push ? ` · <span class="ok">push</span>` : ""}` : "",
          esc(node)].filter(Boolean).join(" · ");
}
// A project's id as it is written (P3), as a roadmap item is R12 and a bug
// B7: the registry's number, never reused, so it names one project for good.
const projId = p => p?.pid ? `P${p.pid}` : "";
// A project (R138, the operator, 25 Oct) is made first, with a name alone,
// and its repositories are added to it; every repository is in one. The
// page reads the projects off the status read's `repos` and each one's
// repositories off its rows, so a project with nothing in it yet has a card.
function projectList(){
  const rows = state?.projects || [];
  return Object.entries(state?.repos || {}).map(([key, r]) => {
    const reps = r.members.map(m => rows.find(p => p.name === m)).filter(Boolean);
    return {...r, key, label: r.name, rows: reps, first: reps[0] || null};
  });
}
// The project a repository is in, or the key itself when it is one: what a
// mark, a lock and the project's own actions are kept by.
function reposOf(name){
  if (state?.repos?.[name]) return name;
  return (state?.projects || []).find(p => p.name === name)?.project || "";
}
// What a project is shown as, from its key or any of its repositories.
const projectName = n => state?.repos?.[reposOf(n)]?.name || projLabel(n);

// The cards the Projects page shows, by key: which are turned over to their
// controls (Edit). The page's while it is on show, never saved.
const pjEditing = new Set();

// One project's card (R138): the front is what is in it and who is working
// there, the back the controls that change it. Edit turns it over in place,
// the two faces sharing one grid cell so the card keeps its size; Back
// turns it back, saving nothing: each control on the back saves its own. A press on the card itself does nothing: its names open
// the repositories' notebooks.
function projectCard(c){
  const pc = colorAttrs(c.color), on = pjEditing.has(c.key);
  return `<div class="pcard pflip${pc.cls}${on ? " flipped" : ""}" data-pkey="${esc(c.key)}"${c.first ? ` data-row="${esc(c.first.name)}"` : ""}${pc.style}>
    <div class="pcface pcfront"${on ? " inert" : ""}>${cardFront(c)}</div>
    <div class="pcface pcback"${on ? "" : " inert"}>${cardBack(c)}</div>
  </div>`;
}
// A project's mark by its name: pressed in where it is set, a press setting
// or clearing it. Archive and pin are a person's sight of it, so they sit
// where the name is read.
function cardMarks(c){
  const pin = c.archived ? "" : `<button type="button" class="eye bare pcmark${c.pinned ? " on" : ""}" data-pmark="${esc(c.key)}" data-on="${c.pinned ? "0" : "1"}"
      aria-pressed="${c.pinned}" aria-label="${c.pinned ? "Unpin" : "Pin"} ${esc(c.name)}" title="${c.pinned ? "pinned: on Home's glance; press to unpin" : "pin it to Home's glance"}">${PIN}</button>`;
  const arch = c.may_archive ? `<button type="button" class="eye bare pcmark${c.archived ? " on" : ""}" data-kmark="${esc(c.key)}" data-on="${c.archived ? "0" : "1"}"
      aria-pressed="${c.archived}" aria-label="${c.archived ? "Unarchive" : "Archive"} ${esc(c.name)}" title="${c.archived
        ? "archived: folded at the foot of this page; press to bring it back" : "archive it: out of sight at the foot of this page, and working as before"}">${ARCHIVE}</button>` : "";
  return pin + arch;
}
// The lock as the card says it: by whom, or read-only where it is not this
// account's to change.
function cardLock(c){
  const said = c.locked ? (c.locked_admin ? "locked by an administrator" : "locked")
    : c.first && writeWhy(c.first) ? "read-only" : "";
  return said ? ` <span class="lockmark" title="${esc(c.locked && c.first ? lockedWhy(c.first) : said)}">${LOCK}${said}</span>` : "";
}
function cardFront(c){
  const first = c.first, cls = {error: "bad", warning: "warn", locked: "locked"};
  const node = first ? first.node_name || first.session_at || "" : "";
  const many = c.rows.length > 1;
  return `<div class="pcname"><span class="name">${esc(c.name)}</span>${cardLock(c)}<span class="sp"></span>${cardMarks(c)}</div>
    <div class="pcmeta"><span class="pcfacts">${[`<span class="pid" title="this project's id, which never changes">${esc(c.pid)}</span>`,
      esc(node)].filter(Boolean).join(" · ")}</span>${first ? projectState(first) : ""}</div>
    <div class="pcrepos">${c.rows.length ? c.rows.map(p => `<div class="pcrepo">
      <button type="button" class="namelink" data-open="${esc(p.name)}" title="open ${esc(p.label || p.name)}'s notebook">${esc(p.label || p.name)}</button>
      <span class="pcfacts">${p.git ? `<span class="pbr">${esc(p.git)}</span>${p.push ? ` · <span class="ok">push</span>` : ""}` : "no git"}</span>
    </div>${p.issues.map(i => `<div class="pnote ${cls[i.level] || ""}">${many ? esc(p.label || p.name) + ": " : ""}${esc(i.text)}</div>`).join("")}`).join("")
      : `<div class="pnote dim">no repository yet${c.may ? ": Add repository makes or clones one" : ""}</div>`}</div>
    ${first ? cardNotes(c) : ""}
    <div class="pcacts actbar">${first ? agentButton(first)
      : `<button type="button" disabled title="Add a repository first">Start agent</button>`}${
      c.may && !c.archived && !state?.session && state?.can?.create !== false ? `<button type="button" data-repadd="${esc(c.key)}">Add repository</button>` : ""}
      <button type="button" data-pedit="${esc(c.key)}" aria-expanded="false">Edit</button></div>`;
}
// What the card says besides its repositories, from its first one, where a
// session runs: mapping, a phone lent, tests running, the one notice.
function cardNotes(c){
  const p = c.first, m = state?.mapping?.[p.name];
  return `${m ? (m.running ? `<div class="pnote dim">mapping the code<span class="dots"></span>${m.for > 4 ? ` · ${m.for}s` : ""}</div>`
        : m.error ? `<div class="pnote warn">the code map did not build: ${esc(m.error)}</div>`
        : `<div class="pnote dim">mapped ${m.files} file${m.files === 1 ? "" : "s"} in ${m.took}s</div>`) : ""}
    ${p.phone?.lease?.project === p.name ? `<div class="pnote dim">${esc(p.phone.model || "a phone")} lent here by ${
        esc(p.phone.lease.by_name || p.phone.owner)}${p.phone.lease.left != null ? `, ${Math.max(1, Math.round(p.phone.lease.left / 60))} min left` : ""}: each command asks ${
        p.phone.mine ? "you" : esc(p.phone.owner)}</div>` : ""}
    ${p.testing ? `<div class="pnote dim">tests running, started ${esc(ago(p.testing.since))}</div>` : ""}
    ${projectNote(p)}`;
}
// The back: the project's name with its pencil, each repository with the
// icons that change it (a shell in it, its git host, rename, move to another
// project, delete), and the project's own controls along the foot. No menu:
// everything is a press away (the operator, 25 Oct).
function cardBack(c){
  const first = c.first, may = c.may && !state?.session;
  const ic = (attr, val, label, icon, extra = "") => `<button type="button" class="eye bare" ${attr}="${esc(val)}" aria-label="${esc(label)}" title="${esc(label)}"${extra}>${icon}</button>`;
  const rows = c.rows.map(p => {
    const n = p.label || p.name, mine = !notMine(p) && !writeWhy(p);
    return `<div class="pcrepo"><span class="name">${esc(n)}</span><span class="sp"></span>
      ${mayShell() && !notMine(p) ? ic("data-s", p.name, `A shell in ${n}`, TERM, gitReadyFor(p) ? "" : " disabled") : ""}
      ${p.git_ok && !isBroken(p) && state?.can?.["git-auth"] !== false ? ic("data-l", p.name, p.linked ? `${p.forge_name || "Remote"} settings for ${n}` : `Link ${n} to a git host`, LINK) : ""}
      ${p.phone?.mine ? ic("data-ph", p.name, p.phone.lease?.project === p.name ? `Take your phone back from ${n}` : `Lend your phone to ${n}`,
                           TOOL_ICONS.phone, phoneWhy(p) ? " disabled" : "") : ""}
      ${mine ? ic("data-rrn", p.name, `Rename ${n}`, PENCIL) : ""}
      ${may ? ic("data-rmove", p.name, `Move ${n} to another project`, MOVE) : ""}
      ${mine && !p.trash_why ? ic("data-del", p.name, `Delete ${n}: to the trash`, BIN, ' data-danger="1"') : ""}</div>`;
  }).join("");
  // The foot is one line of icons at every width (the operator, 25 Oct: one
  // line on either side), each named for a screen reader and a pointer's
  // hover; Pin and Archive are by the name on the front, a press away.
  const fb = (attr, val, label, icon, extra = "") => `<button type="button" class="ic" ${attr}="${esc(val)}" aria-label="${esc(label)}" title="${esc(label)}"${extra}>${icon}</button>`;
  const tone = colorTone(c.color);
  const foot = [
    fb("data-pcolor", c.key, c.color ? `Color: ${c.color}` : "Color", SWATCH, tone ? ` data-sw style="--sw:${tone}"` : ""),
    c.archived ? "" : fb("data-pgroup", c.key, c.group ? `Group: ${c.group}` : "Group", TAG),
    c.may_lock ? fb("data-lock", c.key, lockLabel(c), c.locked ? LOCK : LOCK_OPEN, ` data-on="${c.locked ? "0" : "1"}" aria-pressed="${!!c.locked}"`) : "",
    first && first.mine !== false ? fb("data-bug", first.name, "Report bug", BUG) : "",
    first ? fb("data-rn", first.name, "Settings", GEAR) : "",
    may && !c.rows.length ? fb("data-pdel", c.key, "Delete project", BIN, ' data-danger="1"') : "",
  ].filter(Boolean).join("");
  return `<div class="pcname"><span class="name">${esc(c.name)}</span>${may ? ic("data-prn", c.key, `Rename ${c.name}`, PENCIL) : ""}
      <span class="sp"></span><span class="actbar"><button type="button" data-pedit="${esc(c.key)}" aria-expanded="true">Back</button></span></div>
    <div class="pcrepos">${rows || `<div class="pnote dim">no repository yet</div>`}</div>
    <div class="pcacts actbar pcfoot">${foot}</div>`;
}
// The cards of a list of projects.
const projectCards = list => list.map(projectCard).join("");

// The page come on show again (its kind's open): a card turned over before
// it was left is back on its front. The page is kept while another is on
// show, so its cards are drawn again here rather than built afresh.
function projectsShown(){
  if (!pjEditing.size) return;
  pjEditing.clear();
  drawProjects(state?.projects || []);
}

// A press on a card that changes what it holds (a mark, its color, its
// group, a name) arms its fade: the next draw that changes that card fades
// its face through (faceFade) rather than cutting to the new one. A press
// that opens somewhere else does not.
const PJ_ELSEWHERE = "[data-pedit],[data-open],[data-c],[data-s],[data-rn],[data-bug],[data-l],[data-ph],[data-tcinst],[data-repadd]";
let pjFade = null;               // {key, was: the card's markup at the press}
function pjFadeArm(e){
  const b = e.target.closest?.(".pcard button");
  if (!b || b.matches(PJ_ELSEWHERE) || b.closest(".askline, .pcpop")) return;
  const key = b.closest(".pcard").dataset.pkey, c = projectList().find(x => x.key === key);
  if (c) pjFade = {key, was: projectCard(c)};
}

// Turn a card over, or back, in place: the class moves and the faces trade
// which one a press and a screen reader reach; the next paint draws it so.
function flipCard(key){
  const on = !pjEditing.has(key);
  // One card on its back at a time (the operator, 26 Oct): another turned
  // over goes back to its front, a box open on it cancelled, as Back does.
  if (on) [...pjEditing].filter(k => k !== key).forEach(k => {
    document.querySelectorAll(`.pcard[data-pkey="${CSS.escape(k)}"] :is(.askline, .pcpop)`).forEach(x => x.__done?.(null));
    flipCard(k);
  });
  on ? pjEditing.add(key) : pjEditing.delete(key);
  if (pjFade?.key === key) pjFade = null;    // the turn is its own motion
  const card = document.querySelector(`.pcard[data-pkey="${CSS.escape(key)}"]`);
  if (!card) return;
  card.classList.toggle("flipped", on);
  card.querySelector(".pcfront").inert = on;
  card.querySelector(".pcback").inert = !on;
  card.querySelectorAll("[data-pedit]").forEach(b => b.setAttribute("aria-expanded", String(on)));
  // Drawn again once it has turned, so the grid's markup says so: the next
  // poll otherwise finds it changed and redraws the card, taking a box open
  // on its back (Group, a rename, a move) with it.
  clearTimeout(flipCard.t);
  flipCard.t = setTimeout(() => drawProjects(state?.projects || []), 450);
}

// New project (R138): its name, and nothing else; its repositories are
// added on its card.
async function newProjectByName(){
  const said = await ask({title: "New project", field: {label: "Name"}, choices: [{label: "Create", value: true}],
                         text: "Spaces and punctuation are fine in its name. Its repositories are added on its card."});
  const got = said?.text?.trim();
  if (!got) return;
  try{
    const j = await (await postJSON("/api/repos", {action: "create", name: got})).json();
    if (j.error){ notify(j.error, true); return; }
    pjEditing.delete(j.key);
    notify(`${j.name} made: Add repository on its card makes or clones its first one`);
    await refresh();
    showNewCard(j.key);
  }catch(e){ notify("making the project failed: " + failWords(e), true); await refresh(); }
}

// A project just made: the page scrolls to its card wherever the order put
// it, and the card wears a ring in the accent that fades (the operator, 26
// Oct), so the eye lands on it.
function showNewCard(key){
  const card = document.querySelector(`.pane .doc.on .projtab .pcard[data-pkey="${CSS.escape(key)}"]`);
  if (!card) return;
  card.scrollIntoView({block: "center", behavior: noMotion() ? "auto" : "smooth"});
  card.classList.remove("pjnew");
  void card.offsetWidth;
  card.classList.add("pjnew");
  setTimeout(() => card.classList.remove("pjnew"), 2600);
}

// The cards after a change that moves them (a project renamed sorts
// elsewhere): each slides from where it was to where it lands, and the page
// scrolls with the one that changed so it stays in sight, a phone's single
// column above all (the operator, 26 Oct).
function slideCards(key, change){
  const cards = () => document.querySelectorAll(".pane .doc.on .projtab .pcard[data-pkey]");
  const play = flip(cards, el => el.dataset.pkey, 360);
  change();
  document.querySelector(`.pane .doc.on .projtab .pcard[data-pkey="${CSS.escape(key)}"]`)
    ?.scrollIntoView({block: "nearest", behavior: noMotion() ? "auto" : "smooth"});
  play();
}

// The project's name, asked in a box under it: taken at once from the
// answer, where the card sorts by it, without waiting for the next read.
async function renameProjectCard(btn){
  const key = btn.dataset.prn, was = projectName(key);
  const got = await askInline(btn.closest(".pcname"), {label: `Rename ${was} to`, value: was, ok: "Rename"});
  if (got === null || got === was) return;
  try{
    const j = await (await postJSON("/api/repos", {action: "rename", key, to: got})).json();
    if (j.error){ notify(j.error, true); return; }
    slideCards(key, () => applyNow((x, k) => { if (k === key && "members" in x) x.name = j.name || got; }));
    notify(`${was} is now ${j.name || got}`);
  }catch(e){ notify("renaming failed: " + failWords(e), true); }
  await refresh();
}

// A repository's shown name, asked in a box under its row (the folder stays).
async function renameRepository(btn){
  const name = btn.dataset.rrn, was = projLabel(name);
  const got = await askInline(btn.closest(".pcrepo"), {label: `Rename ${was} to`, value: was, ok: "Rename"});
  if (got === null || got === was) return;
  try{
    const j = await (await postJSON("/api/rename", {name, to: got})).json();
    if (j.error){ notify(j.error, true); return; }
    notify(`${was} is now ${j.label || got}`);
  }catch(e){ notify("renaming failed: " + failWords(e), true); }
  await refresh();
}

// A repository into another project, picked from the ones this account may
// change; refused while a session runs on either.
async function moveRepository(btn){
  const name = btn.dataset.rmove, from = reposOf(name);
  const to = projectList().filter(c => c.key !== from && c.may && !c.archived);
  if (!to.length){ notify("there is no other project of yours to move it to: New project makes one", true); return; }
  const got = await askInline(btn.closest(".pcrepo"), {label: `Move ${projLabel(name)} to`, ok: "Move",
                                                       options: to.map(c => c.name)});
  if (!got) return;
  const c = to.find(x => x.name.toLowerCase() === got.toLowerCase());
  if (!c){ notify(`${got} is not a project it can move to`, true); return; }
  let plan;
  try{
    plan = await (await postJSON("/api/repos", {action: "move-check", name, to: c.key})).json();
  }catch(e){ notify("checking the move failed: " + failWords(e), true); return; }
  if (plan.error){ notify(plan.error, true); return; }
  const add = await moveConfirm(plan);
  if (add === null) return;
  try{
    const j = await (await postJSON("/api/repos", {action: "move", name, to: c.key, add_nodes: add})).json();
    if (j.error){ notify(j.error, true); return; }
    const nn = id => plan.nodes.find(n => n.id === id)?.name || id;
    notify(`${projLabel(name)} is in ${j.project}${
      j.added?.length ? `, which now has ${j.added.map(nn).join(" and ")} too` : ""}${
      j.readers?.length ? `; ${j.readers.join(", ")} now read${j.readers.length === 1 ? "s" : ""} it too` : ""}`);
  }catch(e){ notify("moving it failed: " + failWords(e), true); }
  await refresh();
}

// Are you sure, with what the move changes (the operator, 26 Oct): the
// repository takes its new project's node, people and settings, so the
// nodes the project it leaves had and the new one has not are offered to
// bring along, ticked, each saying the dev instances running there; who
// reaches it through the old project alone is named; a session running on
// either is said, and Move waits for it. Resolves with the nodes to add, or
// null for Cancel.
function moveConfirm(plan){
  return new Promise(resolve => {
    let m = document.getElementById("mvmodal");
    if (!m){
      m = document.createElement("div");
      m.id = "mvmodal"; m.className = "modal"; m.hidden = true;
      m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true"); m.setAttribute("aria-labelledby", "mvTitle");
      document.body.appendChild(m);
      armModal(m);
    }
    const what = n => n.as === "hosts" ? "nodes it hosts containers on" : "nodes it works on";
    const dead = plan.node_why || "";
    const busy = (plan.busy || []).length > 0;
    m.innerHTML = `<div class="box"><h3 id="mvTitle">Move ${esc(plan.label)} to ${esc(plan.to)}?</h3>
      <div class="field"><p class="asksaid">It leaves ${esc(plan.from || "no project")}: from now on ${esc(plan.to)}'s node, people and settings apply to it. Its notebook goes with it.</p></div>
      ${plan.nodes.length ? `<div class="field"><div class="lbl">${esc(plan.from)} uses ${plan.nodes.length === 1 ? "a node" : "nodes"} ${esc(plan.to)} does not</div>
        ${plan.nodes.map(n => `<label class="ndcap"><input type="checkbox" data-mvnode="${esc(n.id)}"${dead ? " disabled" : " checked"}> Add ${esc(n.name)} to ${esc(plan.to)}'s ${what(n)}${
          n.instances.length ? `<span class="dim"> (${esc(n.instances.join(", "))} ${n.instances.length === 1 ? "runs" : "run"} there)</span>` : ""}</label>`).join("")}
        ${dead ? `<div class="sub dim">${esc(dead)}</div>` : `<div class="sub dim">Left unticked, a dev instance there stays where it is, and nothing builds or runs on that node for ${esc(plan.label)} until ${esc(plan.to)} has it.</div>`}</div>` : ""}
      ${plan.lose.length ? `<div class="field"><div class="sub warn">${esc(plan.lose.join(", "))} ${plan.lose.length === 1 ? "reaches" : "reach"} it through ${esc(plan.from)} alone and ${plan.lose.length === 1 ? "loses" : "lose"} it: a role on ${esc(plan.to)} keeps it.</div></div>` : ""}
      ${busy ? `<div class="field"><div class="sub warn">${esc(plan.busy.join(", "))} running on ${esc(plan.from)} or ${esc(plan.to)}: end ${plan.busy.length === 1 ? "it" : "them"} first, then move it.</div></div>` : ""}
      ${dlgFoot(`<button type="button" id="mvCancel">Cancel</button>`, `<button type="button" class="primary" id="mvGo"${busy ? " disabled" : ""}>Move</button>`)}</div>`;
    let over = false;
    const done = v => { if (over) return; over = true; m.hidden = true; resolve(v); };
    m.querySelector("#mvCancel").onclick = () => done(null);
    m.querySelector("#mvGo").onclick = () => done([...m.querySelectorAll("[data-mvnode]:checked")].map(i => i.dataset.mvnode));
    m.onclick = e => { if (e.target === m) done(null); };
    m.hidden = false;
    // Escape and the backdrop close it as Cancel does.
    const watch = new MutationObserver(() => { if (m.hidden){ watch.disconnect(); done(null); } });
    watch.observe(m, {attributes: true, attributeFilter: ["hidden", "class"]});
  });
}

// A project with nothing left in it, gone (R138: one with a repository in it
// is refused, and says so).
async function deleteProjectCard(key){
  const n = projectName(key);
  if (!await askYes(`Delete the project ${n}?\n\nIt has no repository in it, so nothing on disk goes.`)) return;
  try{
    const j = await (await postJSON("/api/repos", {action: "delete", key})).json();
    if (j.error){ notify(j.error, true); return; }
    pjEditing.delete(key);
    notify(`${n} is gone`);
  }catch(e){ notify("deleting the project failed: " + failWords(e), true); }
  await refresh();
}

// The card's own presses, beside wireProjectRows' shared ones.
function wireProjectCards(grid){
  grid.querySelectorAll("[data-pedit]").forEach(b => b.onclick = () => flipCard(b.dataset.pedit));
  grid.querySelectorAll("[data-repadd]").forEach(b => b.onclick = () => openAddRepository(b.dataset.repadd));
  grid.querySelectorAll("[data-prn]").forEach(b => b.onclick = () => renameProjectCard(b));
  grid.querySelectorAll("[data-rrn]").forEach(b => b.onclick = () => renameRepository(b));
  grid.querySelectorAll("[data-rmove]").forEach(b => b.onclick = () => moveRepository(b));
  grid.querySelectorAll("[data-pdel]").forEach(b => b.onclick = () => deleteProjectCard(b.dataset.pdel));
  grid.querySelectorAll("[data-pmark]").forEach(b => b.onclick = () => setProjectPinned(b.dataset.pmark, b.dataset.on === "1"));
  grid.querySelectorAll("[data-kmark]").forEach(b => b.onclick = () => setArchived(b.dataset.kmark, b.dataset.on === "1"));
  grid.querySelectorAll("[data-open]").forEach(b => b.onclick = () => openNotebook(b.dataset.open));
}

function renderProjectsInto(i){
  const el = $("doc" + i);
  if (!el) return;
  const ps = projectList();
  // The surface once (docSurface: the bar band, the band list, the quiet
  // footer): its bar is the search, New project and the trash, and the grid
  // under it is what paints on every pass, so typing in the box is not
  // drawn over.
  if (!el.querySelector(".projtab")){
    const d = docSurface(i, "proj");
    d.setBar(`<input id="pjSearch" type="search" placeholder="name, branch or node" aria-label="narrow the projects" autocomplete="off" spellcheck="false">
        <span class="sp"></span>
        <span class="actbar"><button type="button" id="bTrashTab" aria-label="the trash" title="projects you deleted: still on disk under .trash, and still recoverable">${BIN}</button>
        <button type="button" class="primary" id="bNewProjTab" title="a project, by its name: its repositories are added on its card">New project</button></span>`);
    d.list.innerHTML = `<div class="field pjjob" id="pjJob" hidden></div><div id="pjChips"></div><div class="field pgridband"><div id="pjGrid"></div></div>`;
    el.querySelector("#pjGrid").addEventListener("click", pjFadeArm, true);
    el.querySelector("#bNewProjTab").onclick = newProjectByName;
    el.querySelector("#bTrashTab").onclick = openTrash;
    const box = el.querySelector("#pjSearch");
    box.value = pjQuery;
    box.oninput = () => { pjQuery = box.value; renderProjectsInto(i); };
  }
  const grid = el.querySelector("#pjGrid");
  // New project and the trash are not drawn for an account whose roles do
  // not give them (the operator, 21 Oct: what a role does not give is not
  // advertised); the server refuses them the same (B87).
  setHidden(el.querySelector("#bNewProjTab"), state?.can?.create === false);
  setHidden(el.querySelector("#bTrashTab"), state?.can?.trash === false);
  // The project job (a clone, a first push) running or failed, its own
  // band above the grid, where its result will appear.
  const jb = el.querySelector("#pjJob"), jh = projectJobHtml();
  if (paint(jb, jh)) pJobWire();
  setHidden(jb, !jh);
  // The empty case says what to do: an empty workspace is exactly where
  // somebody is about to make their first project.
  if (!ps.length){
    paint(grid, `<div class="empty">${state.admin ? "no project yet: New project makes one"
                                       : "no projects are yours yet: an administrator grants them on the Users page"}</div>`);
    return;
  }
  // The pinned first, each part by name (the operator, 18 Oct, where on 7
  // Oct it was by name alone): what is pinned is what is looked for. Sorted
  // here rather than by the server, which reports the directory order every
  // other reader wants; each group, and the ungrouped, keeps the order.
  const shown = ps.filter(p => projectMatches(p, pjQuery))
    .sort((a, b) => (b.pinned && !b.archived) - (a.pinned && !a.archived) || byProjectName(a, b));
  // The ones in no group first, then each of this account's groups under
  // its name, by name (the operator, 18 Oct); and the archived ones apart,
  // folded at the foot, their own fold whatever group they were in.
  // The chips count every project that is not archived, whatever the search
  // says, so what the search hides is still counted (the chips rule); one
  // in force narrows the grid to its group, and the archived fold is All's.
  const all = ps.filter(p => !p.archived);
  const chips = byProjectGroup(all).map(({group: g, list}) => ({key: g || "none", label: g || "No group", count: list.length}));
  if (pjChip && !chips.some(c => c.key === pjChip)) pjChip = "";
  const cb = el.querySelector("#pjChips");
  if (paint(cb, chips.some(c => c.key !== "none") ? chipBar(chips, pjChip, "data-pjchip") : ""))
    cb.querySelectorAll("[data-pjchip]").forEach(c => c.onclick = () =>
      fadeThrough(".pane .doc.on .projtab #pjGrid > *", () => { pjChip = c.dataset.pjchip; renderProjectsInto(i); }));
  const inChip = p => !pjChip || (pjChip === "none" ? !p.group : p.group === pjChip);
  const live = shown.filter(p => !p.archived && inChip(p)), gone = pjChip ? [] : shown.filter(p => p.archived);
  const grid_ = list => `<div class="pgrid">${projectCards(list)}</div>`;
  const html = byProjectGroup(live).map(({group: g, list}) => {
        if (!g) return grid_(list);
        // The pencil renames the group for this account alone: a group is a
        // person's own label, so it is never anybody else's to move (R273).
        return `<section class="pjgroup" data-group="${esc(g)}"><h3 class="pjgname">${esc(g)} <span class="dim">${list.length}</span>${
          state.session ? "" : `<button type="button" class="eye bare" data-pjgrename="${esc(g)}" aria-label="Rename the group ${esc(g)}" title="Rename">${PENCIL}</button>`
        }</h3>${grid_(list)}</section>`;
      }).join("")
    + (gone.length ? docSection("projects", "archived", "Archived", `${gone.length} project${gone.length === 1 ? "" : "s"}`,
                                grid_(gone), {open: false, cls: "dim", fold: true}) : "");
  // The card a press armed, faded through once its markup has moved.
  const fc = pjFade && ps.find(c => c.key === pjFade.key);
  const fade = fc && projectCard(fc) !== pjFade.was;
  if (fade) pjFade = null;
  let drawn = false;
  const draw = () => { drawn = paint(grid, html || `<div class="empty">nothing matches ${esc(pjQuery)}</div>`); };
  if (fade) fadeThrough(() => grid.querySelectorAll(`.pcard[data-pkey="${CSS.escape(fc.key)}"] > .pcface:not([inert])`), draw);
  else draw();
  if (drawn){
    wireSections(grid);
    wireProjectRows(grid);
    wireProjectCards(grid);
    grid.querySelectorAll("[data-pjgrename]").forEach(b => b.onclick = () => renameProjectGroup(b));
  }
  syncResumeMenu();
}

// A group renamed in a box under its heading, for every project in it
// (R273); Enter saves, Escape leaves it as it was. Delete group, last on
// the box, takes the group away and its projects back to no group (the
// operator, 19 Oct).
async function renameProjectGroup(btn){
  const was = btn.dataset.pjgrename, head = btn.closest(".pjgname");
  const got = await askInline(head, {label: `Rename ${was} to`, value: was, ok: "Rename",
                                     also: {key: "delete", label: "Delete group"}});
  if (got === null || got === was) return;
  const gone = got?.also === "delete";
  try{
    const j = await (await postJSON("/api/project-group", gone ? {delete: was} : {rename: was, to: got})).json();
    if (j.error){ notify(j.error, true); return; }
    applyNow((x, k) => { x.group = (j.groups || {})[k] || ""; });
    notify(gone ? `${was} is gone: its projects are in no group` : `${was} is now ${got}`);
  }catch(e){ notify("group: " + failWords(e), true); }
  refresh();
}

// Whether a session in this project may rebuild its dev instance: the
// project's own setting, off unless somebody turned it on, read from the
// poll rather than fetched so the checkbox is right on the first draw.
// The same three words the notebook's gates use (GATE_MODES), because it is
// the same question: how much of what a session wants to do happens without
// you. `deny` leads, as the default and as the safe end of the dial.
const DEVBUILD_MODES = [["deny", "deny"], ["ask", "ask me"], ["auto", "auto"]];

// What a project's dial says: one of the three words, deny unless a
// record says otherwise.
const devClaudeMode = name => {
  const v = (state?.projects || []).find(p => p.name === name)?.prefs?.devbuild;
  return DEVBUILD_MODES.some(([m]) => m === v) ? v : "deny";
};

// ---- the new-project dialog ------------------------------------------------
// One dialog, three modes: a new local repo, a clone, and linking a project
// to a git host. The host catalog and the agent's keys arrive per open from
// /api/pubkeys. Moved here from index.html with bb map sections in hand: the
// dialog is the Projects feature's. Its fields, its submit and the name
// that follows the address are wired from index.html.

// No cursor is put in a field here, on open or on a tab switch. A dialog that
// focuses something raises the on-screen keyboard with it, which covers half
// of what it just opened, so the field is chosen by the person who wants to
// type in it. `focus` stays in PMODES because it is also the name of the
// field that mode leads with, which pDraw uses.
const PMODES = {
  init:  { title: () => pInto ? `Add a repository to ${projectName(pInto)}` : "New project", btn: "Create", focus: "pName",
           fields: ["pSrcField", "pNameField", "pVersionField", "pNodeField", "pGateField", "pArchiveField", "pAboutField"] },
  clone: { title: () => pInto ? `Add a repository to ${projectName(pInto)}` : "New project", btn: "Create", focus: "pUrl",
           fields: ["pSrcField", "pNameField", "pNodeField", "pGateField", "pUrlField", "pForgeField",
                    "pPushField", "pTokenField", "pKeyField"] },
  link:  { title: () => `Link ${projLabel(pLink)} to a git host`, btn: "Link", focus: "pUrl",
           fields: ["pUrlField", "pForgeField", "pLinkAuthField", "pKeyField",
                    "pTokenField"] },
};

let pMode = "init";

let pLinkAuth = "key";                   // how a link authenticates: key or token

let pLink = null;                        // the project being linked, if any

let pInto = "";                          // the project a repository is added to (R138)

let pKeys = [];                          // the agent's public keys, per open

let pPat = false;                        // can https push authenticate (gh)?

// The host catalog, from the same fetch as the keys. Empty until it lands,
// which is why every reader goes through pForge() rather than indexing it.
let pForges = [];

let pForgeId = "git";

// What the operator has already said their own servers run, by host. Both
// forms ask which host only for an address on a server nobody has answered
// for yet: the second project from the same Gitea is not asked.
let pForgeHosts = {};

// The host the current pick was made for, so a fresh address gets a fresh
// question rather than the last one's answer.
let pAskedHost = "";

// An archive picked, or picked again: its name beside the button, and the
// brief put away, since the archive is where the project starts.
function pArchivePicked(){
  const f = $("pArchive").files[0];
  $("pArchiveName").textContent = f?.name || "none picked";
  if (f) $("pAbout").value = "";
  pDraw();
}

function pDraw(){
  const m = PMODES[pMode];
  $("pTitle").textContent = m.title();
  if (!$("pCreate").disabled) $("pCreate").textContent = m.btn;
  segPick(["pLocal", "pClone"], pMode === "init" ? "pLocal" : pMode === "clone" ? "pClone" : "");
  for (const f of ["pSrcField", "pNameField", "pVersionField", "pArchiveField", "pForgeField",
                   "pUrlField", "pLinkAuthField", "pPushField",
                   "pTokenField", "pKeyField", "pAboutField", "pGateField"])
    $(f).hidden = !m.fields.includes(f);
  // Into a project, its node and dials are the project's already.
  if (pInto){ $("pNodeField").hidden = true; $("pGateField").hidden = true; }
  // A brief says what to build from nothing; an archive is the start, so the
  // field goes once one is picked (the server refuses the pair as well).
  if (pMode === "init" && $("pArchive").files[0]) $("pAboutField").hidden = true;
  pDrawForge();
  // The deploy-key picker only appears when the agent actually holds keys:
  // an empty dropdown would be a question with no answers.
  if (!pKeys.length) $("pKeyField").hidden = true;
  // Linking: the switch decides which of the two fields is asked.
  if (pMode === "link"){
    segPick(["pLinkKey", "pLinkToken"], pLinkAuth === "key" ? "pLinkKey" : pLinkAuth === "token" ? "pLinkToken" : "");
    $("pKeyField").hidden = pLinkAuth !== "key" || !pKeys.length;
    $("pTokenField").hidden = pLinkAuth !== "token";
  }
  // What the token field is about: the address's own host, in both modes.
  const fg = pFg();
  $("pUrlHint").textContent = pMode === "link"
    ? `An empty repository to push ${pLink} to.`
      + ((fg.creates && pLinkAuth === "token") || (pPat && fg.id === "github" && pLinkAuth === "key")
         ? " One that does not exist yet is created, private." : "")
    : "A private repository needs a deploy key or token that already reaches it.";
  $("pNameHint").textContent = pMode === "clone"
    ? "The directory to clone into; change it to keep two checkouts of one repository."
    : "Anything a git host cannot use in a name becomes a dash.";
  $("pPushHint").textContent =
    "Off is read-only. It cannot be turned on later, and only one project may push to a repository.";
  $("pTokenHint").textContent = pMode === "link"
    ? `Used for ${projLabel(pLink)} only.` + (fg.creates ? ` Checked with ${fg.name} first.` : "")
    : "Leave empty for a public repository. Kept for this project alone.";
  $("pToken").placeholder = fg.hint;
  $("pKeyHint").textContent =
    "The key used to push. Add the public key below to the repository's deploy keys."
    + (pPat && (pMode !== "link" || fg.id === "github") ? " With an access token configured, none works too."
       : pMode === "link" ? " No access token is configured for this host, so a key is required." : "");
}

// The source picker moves like the Dashboard | Terminal switch: the incoming
// fields slide in from the chosen tab's side (local is the left tab, clone
// the right), same 220ms ease, same reduced-motion gate: one vocabulary for
// every two-tab switch on the page. Scaled to the dialog: a few pixels, not
// a viewport, because the fields swap inside a box that is not moving.
// The host in an address, as typed: enough to tell a server the catalog
// names from one nobody has answered for. Not a validator: the server parses
// it properly, and this only decides whether to ask a question.
function pUrlHost(url){
  const u = (url || "").trim();
  let m = /^[a-z]+:\/\/(?:[^@/]+@)?([A-Za-z0-9][A-Za-z0-9.:-]*)/i.exec(u);
  if (!m) m = /^(?:[^@:/]+@)?([A-Za-z0-9][A-Za-z0-9.-]*):/.exec(u);
  return m ? m[1].toLowerCase() : "";
}

// Which catalog entry a host names itself as, or null when nobody has said.
const pForgeOf = host => {
  if (!host) return null;
  const bare = host.split(":")[0];
  return pForges.find(f => f.host && f.host.toLowerCase() === bare)
      || pForges.find(f => f.id === pForgeHosts[host]) || null;
};

function pDrawForge(){
  if ($("pForgeField").hidden) return;
  const sel = $("pForge");
  if (sel.dataset.built !== String(pForges.length)){
    sel.innerHTML = `<option value="" hidden>from the address</option>` + pForges.map(f =>
      `<option value="${esc(f.id)}">${f.dev ? devOpt(esc(f.name)) : esc(f.name)}</option>`).join("");
    sel.dataset.built = String(pForges.length);
  }
  // One row under the address in both modes, always there, so nothing pops
  // up as the address is typed (the operator, 13 Oct). The address is the
  // subject and the host is in it, so this is not a second place to type
  // one: the row reads the address back (GitHub names itself, a server
  // answered for once is remembered) and becomes a question only for a
  // server that does not name itself and nobody has answered for. The
  // hint says which it is, so a locked row says why it is locked.
  const host = pUrlHost($("pUrl").value), bare = host.split(":")[0];
  const named = pForgeOf(host);
  sel.disabled = !host || !!named;
  if (!host){
    sel.value = "";
    $("pForgeHint").textContent = "Read from the address above.";
  } else if (named){
    sel.value = named.id;
    $("pForgeHint").textContent = pForges.some(f => f.host && f.host.toLowerCase() === bare)
      ? `${host} names itself.`
      : `Answered before: ${host} runs ${named.name}.`;
  } else {
    // A server nobody has answered for starts on the entry that promises
    // nothing, not on GitHub: the question is what this one runs, and a
    // default that names a different server is an answer nobody gave.
    if (pAskedHost !== host){ pAskedHost = host; pForgeId = "git"; }
    sel.value = pForgeId;
    $("pForgeHint").textContent = `Which software ${host} runs. Asked once per server.`;
  }
  // The address box asks for the shape the push will use: linking by key
  // is ssh, by token https; a clone takes either and shows the ssh form.
  $("pUrl").placeholder = pMode === "link" && pLinkAuth === "token"
    ? "https://github.com/owner/repo.git" : "git@github.com:owner/repo.git";
}

function pSlide(){
  if (noMotion()) return;
  const dx = pMode === "clone" ? "18px" : "-18px";
  for (const f of PMODES[pMode].fields){
    const el = $(f);
    if (f !== "pSrcField" && !el.hidden)
      el.animate([{transform: `translateX(${dx})`, opacity: 0},
                  {transform: "none", opacity: 1}],
                 {duration: 220, easing: "ease"});
  }
}

// The picked entry, or a safe stand-in while the catalog is still in flight:
// the dialog draws before the fetch answers, and a placeholder that promises
// nothing is better than a draw that throws.
const PFORGE_NONE = {id: "", name: "the host", host: "", fixed: false,
                     hint: "an access token", about: "", creates: false};

const pForge = () => pForges.find(f => f.id === pForgeId) || pForges[0]
                     || PFORGE_NONE;

// The host the dialog is about: the address's own wherever it names itself
// or has been answered for, the picked entry for a server nobody has, and
// the entry that promises nothing while there is no address yet.
const pFg = () => {
  const host = pUrlHost($("pUrl").value);
  return pForgeOf(host) || (host ? pForge() : null)
      || pForges.find(f => f.id === "git") || PFORGE_NONE;
};

function pShowKey(){
  const k = pKeys.find(k => k.name === $("pKey").value);
  $("pPubWrap").hidden = !k;
  if (k) $("pPub").textContent = k.pub;
}

// Each open is a generation; closing bumps it too. Everything asynchronous:
// the pubkeys response, a slow clone's outcome: checks the generation before
// touching the dialog, so a request from a closed dialog can neither shut the
// one the operator just reopened nor write its error where the wrong flow
// will wear it. The outcome itself still surfaces, as a toast.
let pGen = 0;

let pFetch = null;                       // this open's /api/pubkeys, parsed

// The four gates on the dialog (roadmap #27), the same table the settings
// dialog draws from, and auto on every open: what a session may enter is
// asked once here so it is a choice made rather than a default found later.
const P_GATE_IDS = {roadmap: "pGateRoadmap", bugs: "pGateBugs", rules: "pGateRules", settings: "pGateSettings",
                    design: "pGateDesign", wiki: "pGateWiki"};
const pGateNow = () => Object.fromEntries(
  Object.entries(P_GATE_IDS).map(([k, id]) => [k, $(id).value || "auto"]));
// What a new project starts on (the operator, 1 Oct). Auto where what a
// session does lands in the notebook or the settings with its history and
// is undone in a press: the roadmap, bugs, rules, build and test, the
// design, the wiki (each page's history is kept), and a report to
// BuilderBot's own tracker. Ask where it reaches
// past that: its container, which runs the project's code on a shared
// machine and publishes ports (ask rather than the deny a project has
// without a choice, so a session can propose a rebuild at all, having no
// docker of its own), a signed build, which leaves, and a signing key,
// which is an app's identity for good.
const P_GATE_DEFAULT = {pGateDocker: "ask", pGateSign: "ask", pGateKeys: "ask", pGateRelease: "ask", pGateReport: "auto"};
function pFillGates(){
  for (const id of [...Object.values(P_GATE_IDS), "pGateDocker", "pGateSign", "pGateKeys", "pGateRelease", "pGateReport"]){
    const el = $(id);
    if (el.dataset.built !== "1"){
      // A report has nothing to hold for approval: auto or deny.
      el.innerHTML = optionList((id === "pGateWiki" ? gateChoices("wiki") : GATE_MODES).filter(([v]) => id !== "pGateReport" || v !== "ask"));
      el.dataset.built = "1";
    }
    el.value = P_GATE_DEFAULT[id] || "auto";
  }
}

function pOpen(mode){
  const gen = ++pGen;
  pMode = mode; pKeys = []; pPat = false; pFillGates(); pDraw();
  $("pName").value = $("pUrl").value = $("pAbout").value = "";
  $("pToken").value = "";
  pAskedHost = "";
  // Every open starts on the entry that promises nothing rather than on
  // whatever the last one picked: the pick is only ever an answer about a
  // server nobody has answered for, and a remembered one would be silent.
  pForgeId = "git";
  $("pPush").checked = false;
  pNameTyped = false;
  $("pNamePreview").hidden = true;
  $("pName").classList.remove("bad");
  $("pNamePreview").classList.remove("bad");
  // The select is emptied, not left as-is: a key picked during a previous
  // open must not ride along invisibly into this one's submit.
  $("pKey").innerHTML = "";
  $("pErrWrap").hidden = $("pPubWrap").hidden = true;
  unbusy($("pCreate"), PMODES[mode].btn);
  $("pmodal").hidden = false;
  pFillNode();
  // Fetched per open, not cached: keys change when the container restarts
  // with a new /secrets/ssh, and a stale list here would offer a key the
  // agent no longer holds. The submit handler awaits pFetch directly, so an
  // early Create still judges auth on the real answer, not the defaults.
  pFetch = fetch("/api/pubkeys").then(r => r.json()).catch(() => null);
  pFetch.then(j => {
    if (gen !== pGen || !j) return;
    pKeys = j.keys || []; pPat = !!j.pat;
    pForges = j.forges || [];
    pForgeHosts = j.hosts || {};
    pTakenDirs = new Set(j.dirs || []);
    if (!pForges.some(f => f.id === pForgeId)) pForgeId = (pForges[0] || {}).id || "";
    $("pKey").innerHTML = optionList([["", `none: ${pPat ? "use the configured access token" : "public repository"}`],
                                      ...pKeys.map(k => k.name)]);
    pShowKey(); pDraw(); pNameShow();
  });
}

// The node picker on New project: the same list the settings dialog
// offers, fetched the first time it is needed. One node is picked for
// the person; several leave the choice open, with none as the last
// option rather than the first.
function pFillNode(){
  const sel = $("pNode"), wrap = $("pNodeField");
  if (!sel || !wrap) return;
  if (nodesList === null){
    const gen = pGen;
    loadNodes().then(() => { if (gen === pGen && !$("pmodal").hidden) pFillNode(); });
  }
  const pick = (nodesList || []).filter(n => n.kind !== "local" && n.state !== "retired" && n.state !== "disabled");
  const shown = !pInto && PMODES[pMode]?.fields.includes("pNodeField") && pick.length > 0;
  wrap.hidden = !shown;
  if (!shown){ sel.innerHTML = ""; return; }
  const was = sel.value;
  sel.innerHTML = pick.map(n => `<option value="${esc(n.id)}">${esc(n.name)}${
      n.config?.own ? " (this machine)" : ""}${n.live === false ? " (quiet)" : ""}</option>`).join("")
    + `<option value="">none: no builds, tests or sessions until one is picked</option>`;
  // Several: the node most projects are bound to, not none. A project born
  // with no node had nowhere to send its container and used to land on the
  // newest enrolled node instead (the operator, 25 Sep).
  sel.value = pick.some(n => n.id === was) ? was
    : pick.length === 1 ? pick[0].id
    : pick.some(n => n.id === nodesDefault) ? nodesDefault : "";
}

// From first run and Getting started: the server makes a project of the
// same name around it. On a project's card it is Add repository, into that
// project (R138), which keeps the project's node and dials and asks neither.
function openNewProject(){ pLink = null; pInto = ""; pOpen("init"); }

function openAddRepository(key){ pLink = null; pInto = key; pOpen("init"); }

function openLinkProject(name){ pLink = name; pOpen("link"); }

function closeNewProject(){ pGen++; $("pmodal").hidden = true; $("pArchive").value = "";
  $("pArchiveName").textContent = "none picked"; $("pVersion").value = "0.1.0"; }

// A stale error must not survive a mode switch: "a name is required" makes
// no sense over a form that no longer asks for one.
const pSwitch = m => { if (pMode === m) return;
  pMode = m; $("pErrWrap").hidden = true; pDraw(); pSlide(); };

// What a typed name becomes. The server sanitizes for real; this is the same
// rule in the other language, so the operator can see the answer before
// pressing anything, and the two agreeing is checked by a test rather than
// hoped for. If they ever disagree the server wins, and the row that appears
// carries the name it actually made.
function pNameShow(){
  const raw = $("pName").value.trim();
  // Cloning with the field left empty takes the repository's name, so a
  // second copy is checked against THAT, not against an empty string. The
  // name shown follows GitHub's rule (ghName, registry.clean_name).
  const typed = raw || (pMode === "clone" ? repoOfUrl($("pUrl").value) : "");
  const eff = ghName(typed);
  // Since R154 a name in use is no refusal: the new project gets a
  // directory of its own and is shown as Name-2 beside the first.
  const shown = new Set((state?.projects || []).map(p => String(p.label || p.name).toLowerCase()));
  let as = eff, n = 2;
  while (as && shown.has(as.toLowerCase())) as = `${eff}-${n++}`;
  // ...and the folder it gets, numbered when any project ever had it,
  // deleted for good included, so a new one never inherits an old one's
  // notebook or containers (R154). Said here, before Create, rather than
  // found afterwards (B63). The list rides on this open's /api/pubkeys.
  const base = pDirOf(typed);
  let dir = base, k = 2;
  while (dir && pTakenDirs.has(dir.toLowerCase())) dir = `${base}-${k++}`;
  const numbered = !!dir && dir !== base && as === eff;
  const heldBy = numbered ? (state?.projects || []).find(p => p.name.toLowerCase() === base.toLowerCase())?.name || "" : "";
  const empty = !!raw && !eff;
  $("pName").classList.toggle("bad", empty);
  $("pNamePreview").classList.toggle("bad", empty);
  $("pNamePreview").hidden = !empty && as === typed && !numbered;
  $("pNamePreview").textContent = empty ? "A name needs at least one letter or digit in it"
    : as !== eff ? `${eff} is already a project's name, so this one is shown as ${as}`
    : numbered ? `Shown as ${as}, in the folder ${dir}: ${heldBy
        // A live project holding the folder is named, not called deleted
        // (B93: rcclone-2 typed said a deleted project had it while it was
        // a live project's folder).
        ? `${projLabel(heldBy)} is in the folder ${base}`
        : `a deleted project had ${base}, and its notebook and containers stay its own`}`
    : `Shown as ${as}: names follow GitHub's rule, letters, digits, - _ and . only`;
}

// The folder a typed name becomes, before any number: projects.sanitize_name
// in this language (a leading dot, dash or underscore dropped, runs of
// dashes one).
function pDirOf(raw){
  return String(raw || "").trim().replace(/[^A-Za-z0-9._-]/g, "-").replace(/-{2,}/g, "-")
    .replace(/^[._-]+/, "").replace(/-+$/, "").slice(0, 100);
}

// The folders a new project may not have (registry.taken_dirs), lowercased,
// from this open's /api/pubkeys.
let pTakenDirs = new Set();

// The repository's own name out of a clone URL: the same rule the server
// falls back to when the name field is empty.
function repoOfUrl(url){
  const last = (url || "").trim().replace(/\/+$/, "").split(/[/:]/).pop() || "";
  return last.endsWith(".git") ? last.slice(0, -4) : last;
}

// The name follows the address until somebody types one. Tracked rather than
// guessed from emptiness: clearing the field is itself a choice, and refilling
// it on the next keystroke of the URL would fight whoever did it.
let pNameTyped = false;

// Create, clone or link: the dialog's one submit, wired to #pCreate in index.html.
async function createProject() {
  // Captured at the click: the dialog can be closed, reopened and switched
  // to another mode while this request runs, and everything below must keep
  // talking about the flow the operator actually submitted.
  const mode = pMode, linkName = pLink, into = pInto, gen = pGen;
  const name = $("pName").value.trim();
  let url = $("pUrl").value.trim();
  const key = $("pKey").value;          // "" until this open's fetch offered any
  const file = mode === "init" ? $("pArchive").files[0] : null;
  const fail = m => gen === pGen
    ? ($("pErr").textContent = m, $("pErrWrap").hidden = false)
    : notify(`${mode === "link" ? projLabel(linkName) : name || mode}: ${m}`, true);
  if (mode === "init"){ if (!name) return fail("a name is required"); }
  else if (!url) return fail("a repository address is required");
  $("pErrWrap").hidden = true;
  const b = $("pCreate");
  busy(b, { init: "Creating", clone: "Starting", link: "Starting" }[mode]);
  try{
    // A push has to authenticate somehow; catching this before the round-trip
    // spares typing a URL into a flow that cannot finish. Judged on the
    // pubkeys answer itself: awaited, so an early Create is not judged on
    // the pre-fetch defaults. (The server refuses it too; this is just the
    // earlier of the two answers.)
    const linkToken = mode === "link" && pLinkAuth === "token" ? $("pToken").value.trim() : "";
    const fg = pFg();
    // The pick is sent only when it was asked: for a server the address
    // names or one answered for before, the server reads the address.
    const forge = pForgeOf(pUrlHost(url)) ? "" : pForgeId;
    if (mode === "link" && pLinkAuth === "token" && !linkToken)
      return fail("an access token for this project: a push has to authenticate somehow");
    if (mode === "link" && pLinkAuth === "key" && !key){
      const auth = await pFetch;
      // The container's PAT is GitHub's and covers nothing else, so it is not
      // an answer for a host it was never minted for.
      if (!(auth && auth.pat && fg.id === "github"))
        return fail((auth && auth.keys || []).length
          ? `no credential is configured for ${fg.name}: pick a deploy key, or switch to an access token`
          : `no deploy key is available for ${fg.name}: switch to an access token, or add a deploy key and try again`);
    }
    // The archive goes first, on its own: the create request is a small
    // JSON body and the upload is not, so the server spools the bytes and
    // hands back an id the create quotes.
    let archive = "";
    if (file){
      busy(b, "Uploading");
      const u = await fetch("/api/upload-archive?name=" + encodeURIComponent(file.name),
                            {method: "POST", body: file});
      const uj = await u.json().catch(() => ({}));
      if (!u.ok) return fail(uj.error || `upload failed (HTTP ${u.status})`);
      archive = uj.id;
      busy(b, "Creating");
    }
    const r = mode === "link"
      ? await fetch("/api/link", {method:"POST",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({name: linkName, url, forge,
                                key: pLinkAuth === "key" ? key : "",
                                token: linkToken})})
      : await fetch("/api/create", {method:"POST",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({name, mode, url, project: into, about: $("pAboutField").hidden ? "" : $("pAbout").value, archive,
                                node: $("pNodeField").hidden ? "" : $("pNode").value,
                                // A starting version, for a fresh tree only: a
                                // clone keeps the history it came with.
                                version: mode === "init" ? $("pVersion").value.trim() : "",
                                gate: $("pGateField").hidden ? null : pGateNow(),
                                devbuild: $("pGateField").hidden ? null : ($("pGateDocker").value || "deny"),
                                sign: $("pGateField").hidden ? null : ($("pGateSign").value || "ask"),
                                keys: $("pGateField").hidden ? null : ($("pGateKeys").value || "ask"),
                                release: $("pGateField").hidden ? null : ($("pGateRelease").value || "ask"),
                                report: $("pGateField").hidden ? null : ($("pGateReport").value || "auto"),
                                key: mode === "clone" ? key : "",
                                forge: mode === "clone" ? forge : "",
                                token: mode === "clone" ? $("pToken").value.trim() : "",
                                push: mode === "clone" && $("pPush").checked})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return fail(j.error || `${mode} failed (HTTP ${r.status})`);
    if (gen === pGen) closeNewProject();
    // Everything that touches the network is a background job now, and it is
    // accepted, not finished. The dialog gets out of the way and the Projects
    // card carries it from here, which is also what happens if this page is
    // closed a second later.
    if (j.started){
      pJobSeen({running: true, kind: mode === "link" ? "link" : "clone",
                name: j.name || linkName, step: "starting", for: 0});
      pJobPoll();
    } else {
      notify(`${mode === "link" ? projLabel(linkName) : j.label || name || j.name} ${mode === "link" ? "linked" : "created"}: ${j.note || "ready"}`);
      refresh();                        // the new state, without waiting a poll
    }
  }catch(e){
    // The request may still be running server-side (a big clone or push
    // outlives a dropped connection), so say to look rather than blindly retry.
    fail("lost the connection; check the Projects card before trying again");
  }finally{
    if (gen === pGen) unbusy(b, PMODES[pMode].btn);
  }
}
