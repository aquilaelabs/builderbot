// The notebook's Permissions view: everything a session may do on this
// project, in one place (the operator, 22 Oct: the dials were split between
// the Settings view's Agents may and the Git view's push policy). Beside
// Overview and Settings in the Overview group.
// One classic script beside index.html, the shape tab-*.js has (docs/nodes.md
// §13): same page, same global scope, one file per notebook view (R60).
//
// A factory rather than a script that runs: makeNotebook calls it per
// notebook with the notebook's element lookup, its state object and its
// project, and takes back the two functions the rest of the notebook calls.

"use strict";

function nbPermsView({$, nb, project, root}){
  const view = () => root.querySelector('.nbview[data-view="permissions"]');
  // The project settings' own section (rn:claude), lent to this view while it
  // is on screen and handed back to its place in the form on the way out
  // (rnDialsHome), so there is one set of fields, one set of handlers and its
  // own Save and Revert, as the Settings view lends the whole form.
  function lendDials(){
    const host = view()?.querySelector(".permdials > .box");
    // Not a fading view's still copy of it (ghostOf), which holds one too.
    const sect = [...document.querySelectorAll('details[data-sect="rn:claude"]')].find(d => !d.closest(".fghost"));
    if (!host || !sect) return;
    if (sect.parentElement === host && rnFor === project) return;
    rnDialsHome();
    // The form read for this project first, as the Settings view does.
    if (rnFor !== project || rnHost) renameProject(project);
    document.getElementById("rnmodal").hidden = true;      // the page's, outside this notebook
    sect.parentElement.insertBefore(document.createComment(RN_DIALS_MARK), sect);
    sect.open = true;
    host.appendChild(sect);
  }

  // What a session may do with the remote (roadmap R36), moved here from
  // the Git view: staged until Apply, enforced on the relay; a local commit
  // or merge cannot be forbidden, and the bar says so. The third is whether
  // a push with lines that look sensitive waits on the bell for a person
  // (R219) or goes without the hold.
  let draft = {};
  const GITPOL_DEFAULT = {push: "allow", main: "deny", scan: "hold"};   // prefs.GITPOL_DEFAULT
  function drawPush(){
    const host = view()?.querySelector(".permgit");
    if (!host) return;
    const p = (state?.projects || []).find(x => x.name === project);
    const locked = !!p?.locked_me || !!projWriteWhy(project);
    const saved = p?.prefs?.gitpol || {}, pol = {...saved, ...draft};
    const dirty = Object.keys(draft).length > 0;
    const body = `<div class="row stack2 gpolicy"><div class="grow">
        <div class="prefrow ctlrow">
          <label class="pick">Push its branches <select data-gitpol="push"${locked ? " disabled" : ""}>${optionList(["allow", "deny"], pol.push || "allow")}</select></label>
          <label class="pick">Push to its main branch <select data-gitpol="main"${locked ? " disabled" : ""}>${optionList(["allow", "deny"], pol.main || "deny")}</select></label>
          <label class="pick">Hold a push that looks sensitive <select data-gitpol="scan"${locked ? " disabled" : ""}>${optionList(["hold", "off"], pol.scan || "hold")}</select></label>
        </div>
        <div class="actbar">
          <span class="state">${locked ? "this project is locked: its owner changes these" : `its own branches, one at a time ${helpIcon("Applies to pushes only. Tags, deletions and remote-only branches stay yours; commits and merges here are always allowed.")}`}</span>
          <button type="button" class="permGitApply"${dirty && !locked ? "" : " disabled"}>Apply</button>
        </div></div></div>`;
    const html = docSection("permissions", "push", "Pushing", `${pol.push || "allow"} · ${pol.main || "deny"}${pol.scan === "off" ? " · unheld" : ""}`, body);
    if (host.dataset.drawn === html) return;
    host.innerHTML = html; host.dataset.drawn = html;
    wireSections(host);
    host.querySelectorAll("[data-gitpol]").forEach(sel => sel.onchange = () => {
      if (sel.value === (saved[sel.dataset.gitpol] || GITPOL_DEFAULT[sel.dataset.gitpol])) delete draft[sel.dataset.gitpol];
      else draft[sel.dataset.gitpol] = sel.value;
      const b = host.querySelector(".permGitApply"); if (b) b.disabled = !Object.keys(draft).length;
    });
    const pa = host.querySelector(".permGitApply");
    if (pa) pa.onclick = async () => {
      busy(pa, "Applying");
      try{
        const j = await (await postJSON("/api/prefs", {project, gitpol: {...pol, ...draft}})).json();
        if (j.error) return notify(j.error, true);
        draft = {};
        notify("saved");
        refresh();
      }catch(e){ notify("policy: " + failWords(e), true); }
      finally{ if (pa.isConnected) unbusy(pa, "Apply"); drawPush(); }
    };
  }

  // The glance (R109): how many of the dials a session meets on its own,
  // asked first, or not at all, read off the section's own pickers, and the
  // push policy as its line.
  function drawGlance(){
    const v = view(), hint = v?.querySelector(".nbglance");
    if (!hint) return;
    const n = {auto: 0, ask: 0, deny: 0};
    v.querySelectorAll('details[data-sect="rn:claude"] select').forEach(s => { if (s.value in n) n[s.value]++; });
    const pol = {...((state?.projects || []).find(x => x.name === project)?.prefs?.gitpol || {})};
    viewGlance(hint, [{label: "on its own", value: n.auto}, {label: "asks first", value: n.ask},
                      {label: "may not", value: n.deny}],
      `pushing its branches ${pol.push || "allow"}, to main ${pol.main || "deny"}`);
  }
  function loadPerms(){ lendDials(); drawPush(); drawGlance(); }
  function leavePerms(){ rnDialsHome(); }
  return {loadPerms, leavePerms, drawPush: () => { drawPush(); drawGlance(); }};
}
