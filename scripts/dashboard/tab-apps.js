// The Apps page (R272 step 5), under Build after the CI runner (the
// operator, 19 Oct: the software is a builder's, where the devices signed
// in are the last of the person's Profile): the apps this controller offers for
// a person's own machines, each with its version beside the controller's,
// Download and how to connect it. Its own classic script beside index.html,
// per the new-surface rule; chrome from docSurface().
//
// What is offered is the Settings page's (apps_* switches, apps.py); what
// is held is what the controller fetched from its release and checked. A
// person downloads from here, and an app that finds itself behind comes
// here, or fetches from /apps itself (the companion, R270 step 9).

"use strict";

let devApps = null, devAppsRev = 0;

function openAppsTab(){
  openTab({kind: "apps", arg: "__apps", label: "Apps"});
}

// What the controller offers and holds (apps.view), for this page and the
// Controller page's Apps section.
async function loadApps(){
  // Switched off on this install (R81): the route refuses, so it is not asked.
  if (featureOff("apps")){ devAppsRev++; return; }
  try{
    const r = await bootFetch("/api/apps");
    const j = await r.json();
    if (!j.error) devApps = j;
  }catch(e){ /* each page says it could not read them */ }
  devAppsRev++;
  if (tabs.some(t => t.kind === "apps" || t.kind === "settings")) drawPanes();
}

// How an app is connected once it is installed: the controller's address
// is the one thing each asks for, written where it is typed.
function devHow(name){
  const at = `<code>${esc(location.origin)}</code>`;
  return {
    android: `Install it, open it and sign in at ${at} with your name and password.`,
    vscode: `In VS Code: Extensions, the ⋯ menu, Install from VSIX; then BuilderBot: Connect, at ${at}.`,
    companion: `Run it, sign in at ${at} with your name and password, and pick a project and a folder.`,
  }[name] || "";
}

// One app: what it does, the version held beside the controller's, its
// download and how to connect it; or why it is not here yet.
function devAppRow(a){
  const v = devApps?.version || "";
  const [first, ...rest] = a.files || [];
  const behind = a.version && v && !v.startsWith(a.version);
  return `<div class="row stack2 devapp" data-devapp="${esc(a.name)}"><div class="grow">
      <div class="name">${esc(a.title)}${a.dev ? devMark() : ""}${a.version ? ` <span class="pill${behind ? " warn" : ""}">${esc(a.version)}</span>` : ""}</div>
      <div class="hint">${esc(a.does)}</div>
      ${first ? `<div class="sub">${devHow(a.name)}</div>`
        : a.absent ? `<div class="sub warn">Not in ${esc(a.absent)}: that release does not carry it.</div>`
        : `<div class="sub warn">Not fetched yet${devApps?.problem ? "" : ": the controller looks at its release a while after it starts, then daily"}.</div>`}
      ${rest.length ? `<div class="sub dim">Also: ${rest.map(f => `<a href="${esc(f.url)}" download>${esc(f.file)}</a>`).join(", ")}</div>` : ""}
    </div>
    <div class="actbar">${first ? `<a class="btn primary" href="${esc(first.url)}" download title="${esc(first.file)} · sha256 ${esc(first.sha256.slice(0, 12))}…">Download</a>`
      : `<button type="button" class="primary" disabled>Download</button>`}</div></div>`;
}

// The list under its head, drawn the same by the page and its placeholder.
function appsSection(body, count){
  return docSection("apps", "list", "Apps", count, body);
}

function renderAppsInto(i){
  const d = docSurface(i, "apps");
  if (!d) return;
  // The apps' downloads switched off on this install (R81): its sentence,
  // and nothing asked of a route that would refuse.
  if (featureOff("apps")){
    d.setBar("");
    d.list.innerHTML = appsSection(`<div class="field">${deadWhy(featureOff("apps"))}</div>`, "");
    return;
  }
  if (!devApps){
    d.setBar("");
    d.list.innerHTML = skTpl(pageHead({title: "This controller", facts: [["Version", GHOST], ["Apps offered", GHOST]]})
      + appsSection(skRows(3), ""));
    return;
  }
  const offered = (devApps.apps || []).filter(a => a.offered);
  // The controller these are offered by, as a head (the operator, 25 Oct).
  d.setBar("");
  d.list.innerHTML = pageHead({title: "This controller", facts: [["Version", devApps.version || "unstamped"],
                                                                 ["Apps offered", String(offered.length)]]}) + appsSection(offered.length ? (devApps.problem ? `<div class="field"><div class="notice warn">The controller's last look at its release did not work: ${
      esc(devApps.problem)}</div></div>` : "") + offered.map(devAppRow).join("")
    : `<div class="empty">This controller offers no apps: an administrator picks them on the Controller page, under Apps.</div>`,
    String(offered.length || ""));
  wireSections(d.list);
}
