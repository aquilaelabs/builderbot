// The Users tab: who may sign in, and which projects they see. Step 3 of
// roadmap #22; the design and the reasoning are docs/users.md and are not
// repeated here. Its own classic script beside index.html, per the
// new-surface rule — same page, same global scope, one file per surface.
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs;
// this file fills slots. Every rule about WHO may do WHAT lives on the server
// (users.py): a row that cannot be deleted is drawn without the control and
// says why, rather than being offered one that fails — but the store refuses
// it regardless, because `bb users` reaches the same rules from a shell.

let usersList = null;            // last answer, or null before the first
let usersRev = 0;                // bumped when it changes, so panes repaint
let usersErr = "";
let usersMeta = {owner: "", me: "", roles: [], projects: []};
let usersEditing = "";           // the row whose projects are open, if any
// A role picked and not yet saved, per account: the tab redraws on the
// poll, and a pick that a redraw put back would be a Save that could never
// be pressed. Cleared by the save, or by picking the saved role again.
const usersRoleDraft = {};

function openUsersTab(){
  openTab({kind: "users", arg: "__users", label: "Users"});
  loadUsers();
}

async function loadUsers(){
  try{
    const j = await (await fetch("/api/users")).json();
    usersErr = j.error || "";
    usersList = j.users || [];
    usersMeta = {owner: j.owner || "", me: j.me || "",
                 roles: j.roles || [], projects: j.projects || []};
  }catch(e){
    usersErr = String(e);
    usersList = usersList || [];
  }
  usersRev++;
  drawPanes();
}

async function usersAct(body){
  try{
    const r = await fetch("/api/users", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) return notify(j.error || `failed (HTTP ${r.status})`, true);
    notify(body.action === "remove" ? `${body.name} removed`
         : body.action === "add" ? `${body.name} added`
         : `${body.name} updated`);
  }catch(e){ return notify(String(e), true); }
  await loadUsers();
}

// One row. The owner's is the one with rules attached, and it says them
// rather than showing controls that would be refused.
function userRow(u){
  const isOwner = u.role === "owner";
  const isMe = u.name === usersMeta.me;
  const seen = !u.seen ? "never signed in" : "last seen " + ago(u.seen);
  const scope = u.role === "user"
    ? (u.projects.length
        ? `<span class="sub">sees</span> ` + u.projects.map(
            p => `<span class="pill">${esc(p)}</span>`).join(" ")
        : `<span class="sub dim">sees nothing yet — it can sign in, and every
             project is hidden until one is given</span>`)
    : `<span class="sub">sees every project</span>`;
  return `<div class="row stack2 urow" data-user="${esc(u.name)}">
    <div class="grow">
      <div class="name">${esc(u.name)}
        <span class="pill">${esc(u.role)}</span>${
        isMe ? ` <span class="pill">you</span>` : ""}</div>
      <div class="uscope">${scope}</div>
      <div class="sub${u.claude_shared_with?.length ? " warn" : " dim"}">${u.claude
        ? `signed in to Claude as ${esc(u.claude)}${u.claude_shared_with?.length
            ? ` — the same Claude account as ${u.claude_shared_with.map(esc).join(", ")}: fine while one person is behind both, since Anthropic's terms allow one person per Claude account`
            : ""}`
        : "no Claude login yet — its sessions sign in on first use"}</div>
      ${isOwner ? `<div class="sub dim">The owner cannot be deleted or given a
        different role — it is the account every other rule here is a guard rail
        around. Its name can be changed.</div>` : ""}
    </div>
    <div class="actbar">
      <span class="state">${esc(seen)}</span>
      ${u.role === "user" ? `<button type="button" data-uprojects="${esc(u.name)}"
        >${usersEditing === u.name ? "Done" : "Projects"}</button>` : ""}
      ${isOwner ? "" : `<select data-urole="${esc(u.name)}" data-was="${esc(u.role)}"
        aria-label="role for ${esc(u.name)}">${
        usersMeta.roles.filter(r => r !== "owner").map(r =>
          `<option value="${esc(r)}"${r === (usersRoleDraft[u.name] || u.role) ? " selected" : ""}>${esc(r)}</option>`).join("")}
      </select><button type="button" data-urolesave="${esc(u.name)}"${
        usersRoleDraft[u.name] && usersRoleDraft[u.name] !== u.role ? "" : " disabled"}
        title="save the role">Save</button>`}
      <button type="button" data-upasswd="${esc(u.name)}">Password</button>
      ${isOwner
        ? `<button type="button" class="danger" disabled
             title="the owner cannot be deleted — rename it instead">Remove</button>`
        : `<button type="button" class="danger" data-uremove="${esc(u.name)}">Remove</button>`}
    </div>
    ${usersEditing === u.name ? usersProjectPicker(u) : ""}
  </div>`;
}

// Which projects a `user` account may see. Only the ones the admin doing the
// giving can see themselves — the server filters again, so this is the honest
// list rather than the enforcing one.
function usersProjectPicker(u){
  const have = new Set(u.projects);
  return `<div class="upick grow">
    ${usersMeta.projects.length
      ? usersMeta.projects.map(p => `<label class="pkg"><input type="checkbox"
          data-uproj="${esc(p)}"${have.has(p) ? " checked" : ""}>
          <span class="grow"><span class="nm">${esc(p)}</span></span></label>`).join("")
      : `<div class="sub">no projects to give</div>`}
    <div class="actbar"><button type="button" class="primary" data-usave="${esc(u.name)}"
      >Save projects</button></div>
  </div>`;
}

function renderUsersInto(i){
  const d = docSurface(i, "users");
  if (!d) return;
  d.setBar(`<span class="dim">who may sign in here, and which projects they
    see. A project somebody was not given does not appear for them at all —
    not greyed out, absent.</span>`);
  if (usersList === null){
    d.list.innerHTML = `<div class="row"><div class="sub">loading<span class="dots"></span></div></div>`;
    loadUsers();
    return;
  }
  d.list.innerHTML = `
    ${usersErr ? `<div class="row bad"><div class="grow">${esc(usersErr)}</div></div>` : ""}
    ${usersList.map(userRow).join("")}
    ${docSection("users", "roles", "What an account gets", "", `
        <div class="sub">Each account has its own home: terminals, shell history,
          Claude login and memories. The owner keeps this container's original one.</div>
        <div class="sub">Two people on one project each get a worktree on a branch of
          their own. The notebook stays shared; memories do not.</div>
        <div class="sub">A <b>user</b> has no shell: their Claude session is a console,
          and Docker and packages are read-only apart from Rebuild and Abort on their
          own projects.</div>
        <div class="sub warn">An <b>admin</b> has a shell, which reaches every account's
          files. Give that role to people you would give the server to.</div>`)}
    ${docSection("users", "add", "Add somebody", "", `
        <div class="sub">An <b>admin</b> can do anything except act on the owner. A
          <b>user</b> gets only the projects you give them, and cannot delete, rename
          or move one to another node.</div>
        <div class="sub">An admin sees every project and works on the ones on their
          list; a user sees only their list.</div>
        <div class="actbar uadd">
          <input id="uNewName" placeholder="name" autocomplete="off" aria-label="new account name">
          <input id="uNewPw" type="password" placeholder="password"
            autocomplete="new-password" aria-label="password">
          <select id="uNewRole" aria-label="role">${
            usersMeta.roles.filter(r => r !== "owner").map(r =>
              // `user` selected, not merely first: the roles run owner, admin,
              // user, so the browser's own default would be the MOST privileged
              // of the two on offer. Adding somebody should start at the least.
              `<option value="${esc(r)}"${r === "user" ? " selected" : ""}
                >${esc(r)}</option>`).join("")}</select>
          <button type="button" class="primary" id="uAdd">Add</button>
        </div>`)}`;
  wireSections(d.list);
  d.setFoot(`Locked out? <code>bb users passwd &lt;name&gt;</code> in the
    container resets a password, and <code>bb users add</code> makes an account
    when there are none. That path exists because this one can fail.`);
  wireUsers(d.el);
}

function wireUsers(el){
  el.querySelectorAll("[data-uremove]").forEach(b => b.onclick = () => {
    const n = b.dataset.uremove;
    if (confirm(`Remove ${n}? They lose access immediately — any session they `
                + `have signed in with stops working on the next request.`))
      usersAct({action: "remove", name: n});
  });
  // A role is saved on Save, not on the change: the select is a question
  // and the button is the answer (docs/design-language.md, Settings).
  el.querySelectorAll("[data-urole]").forEach(sel => sel.onchange = () => {
    if (sel.value === sel.dataset.was) delete usersRoleDraft[sel.dataset.urole];
    else usersRoleDraft[sel.dataset.urole] = sel.value;
    const b = el.querySelector(`[data-urolesave="${CSS.escape(sel.dataset.urole)}"]`);
    if (b) b.disabled = sel.value === sel.dataset.was;
  });
  el.querySelectorAll("[data-urolesave]").forEach(b => b.onclick = async () => {
    const name = b.dataset.urolesave, role = usersRoleDraft[name];
    if (!role) return;
    delete usersRoleDraft[name];
    await usersAct({action: "role", name, role});
  });
  el.querySelectorAll("[data-upasswd]").forEach(b => b.onclick = () => {
    const n = b.dataset.upasswd;
    const pw = prompt(`New password for ${n} — at least 8 characters.\n\n`
                      + `Any session signed in as ${n} stops working at once.`);
    if (pw) usersAct({action: "passwd", name: n, password: pw});
  });
  el.querySelectorAll("[data-uprojects]").forEach(b => b.onclick = () => {
    usersEditing = usersEditing === b.dataset.uprojects ? "" : b.dataset.uprojects;
    usersRev++; drawPanes();
  });
  el.querySelectorAll("[data-usave]").forEach(b => b.onclick = () => {
    const picked = [...el.querySelectorAll("[data-uproj]")]
      .filter(c => c.checked).map(c => c.dataset.uproj);
    usersEditing = "";
    usersAct({action: "projects", name: b.dataset.usave, projects: picked});
  });
  const add = el.querySelector("#uAdd");
  if (add) add.onclick = () => {
    const name = el.querySelector("#uNewName").value.trim();
    const pw = el.querySelector("#uNewPw").value;
    if (!name || !pw) return notify("a name and a password", true);
    usersAct({action: "add", name, password: pw,
              role: el.querySelector("#uNewRole").value});
  };
}
