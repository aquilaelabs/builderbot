// The Profile tab: the signed-in account's own settings — who they are,
// how their commits are signed, and their password. Its own classic script
// beside index.html, per the new-surface rule; chrome from docSurface(),
// conformance held by uniform.mjs.
//
// Per ACCOUNT, and only ever the account asking: the server answers
// /api/profile for whoever is signed in, so there is nothing here to pick
// and nothing an administrator does on somebody's behalf — that is the
// Users tab. The commit identity lives here rather than in a project's
// settings because two people on one project are two authors: it reaches
// every session this account starts as git's environment, which outranks
// whatever a repository has configured.
let profile = null, profileRev = 0;
// Typed and not yet saved, kept across the poll's redraws: a field that
// emptied itself mid-sentence would be unusable (docs/design-language.md,
// Settings — nothing takes effect until Save).
const profileDraft = {};

function openProfileTab(){
  openTab({kind: "profile", arg: "__profile", label: "Profile"});
}

async function loadProfile(){
  try{
    const r = await fetch("/api/profile");
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    profile = j;
  }catch(e){ notify("profile: " + e, true); return; }
  profileRev++;
  if (tabs.some(t => t.kind === "profile")) drawPanes();
}

const PROFILE_FIELDS = [
  ["full_name", "Name", "the name people see — not the account name you sign in with"],
  ["email", "Email", "how to reach you; nothing here sends mail"],
  ["git_name", "Git name", "on your commits; blank means the name above"],
  ["git_email", "Git email", "on your commits; blank means the email above. A GitHub noreply address keeps yours out of the log"],
];

function renderProfileInto(i){
  const d = docSurface(i, "profile");
  if (!d) return;
  if (!profile){
    d.list.innerHTML = `<div class="loading">loading…</div>`;
    return;
  }
  const p = profile.profile || {}, g = profile.git || {};
  const val = k => profileDraft[k] ?? p[k] ?? "";
  const dirty = PROFILE_FIELDS.some(([k]) => (profileDraft[k] ?? p[k] ?? "") !== (p[k] ?? ""));
  d.setBar(`<span class="dim">${esc(profile.name)} · ${esc(profile.role)}${
    profile.claude ? ` · Claude: ${esc(profile.claude)}` : ""}</span>`);
  d.list.innerHTML = `
    <div class="row stack2">
      <div class="grow">
        <h4>Who you are</h4>
        <div class="logset">
          ${PROFILE_FIELDS.map(([k, label, hint]) => `
            <div class="logdays setrow">
              <label for="pf_${k}">${esc(label)}</label>
              <input id="pf_${k}" type="text" data-pf="${k}" value="${esc(val(k))}"
                     spellcheck="false" autocomplete="off">
            </div><div class="dim">${esc(hint)}</div>`).join("")}
          <div class="actbar">
            <span class="state">commits are signed ${esc(g.name || "—")}${g.email ? ` &lt;${esc(g.email)}&gt;` : ""}</span>
            <button type="button" id="pfSave" class="primary"${dirty ? "" : " disabled"}>Save</button>
          </div>
        </div>
      </div>
    </div>
    <div class="row stack2">
      <div class="grow">
        <h4>Password</h4>
        <div class="logset">
          <div class="logdays setrow">
            <label for="pfCur">Current</label>
            <input id="pfCur" type="password" autocomplete="current-password">
          </div>
          <div class="logdays setrow">
            <label for="pfNew">New</label>
            <input id="pfNew" type="password" autocomplete="new-password">
          </div>
          <div class="logdays setrow">
            <label for="pfNew2">Again</label>
            <input id="pfNew2" type="password" autocomplete="new-password">
          </div>
          <div class="actbar">
            <span class="state">at least 8 characters; every browser signed in as you signs out</span>
            <button type="button" id="pfPasswd">Change password</button>
          </div>
        </div>
      </div>
    </div>`;
  d.setFoot(`Your commits carry the git name and email above in every session and shell you open, whichever project — the account name stays what you sign in with.`);
  wireProfile(d.el);
}

function wireProfile(root){
  const p = profile?.profile || {};
  root.querySelectorAll("[data-pf]").forEach(inp => inp.oninput = () => {
    const k = inp.dataset.pf;
    if (inp.value === (p[k] ?? "")) delete profileDraft[k];
    else profileDraft[k] = inp.value;
    const b = root.querySelector("#pfSave");
    if (b) b.disabled = !Object.keys(profileDraft).length;
  });
  const save = root.querySelector("#pfSave");
  if (save) save.onclick = async () => {
    const body = {};
    root.querySelectorAll("[data-pf]").forEach(i => { body[i.dataset.pf] = i.value; });
    busy(save, "Saving");
    try{
      const r = await fetch("/api/profile", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: "save", profile: body})});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      for (const k of Object.keys(profileDraft)) delete profileDraft[k];
      notify("saved — your next session and shell carry it");
      await loadProfile();
    }catch(e){ notify("profile: " + e, true); }
    finally{ if (save.isConnected) unbusy(save, "Save"); }
  };
  const pw = root.querySelector("#pfPasswd");
  if (pw) pw.onclick = async () => {
    const cur = root.querySelector("#pfCur").value, a = root.querySelector("#pfNew").value,
          b2 = root.querySelector("#pfNew2").value;
    if (a.length < 8) return notify("a password is at least 8 characters", true);
    if (a !== b2) return notify("the two new passwords differ", true);
    busy(pw, "Changing");
    try{
      const r = await fetch("/api/profile", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: "password", current: cur, password: a})});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      notify("password changed — sign in again where you are asked to");
      ["pfCur", "pfNew", "pfNew2"].forEach(id => { const el = root.querySelector("#" + id); if (el) el.value = ""; });
    }catch(e){ notify("profile: " + e, true); }
    finally{ if (pw.isConnected) unbusy(pw, "Change password"); }
  };
}
