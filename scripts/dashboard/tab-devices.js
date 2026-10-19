// The Devices page (R272 step 5), under Settings beside Profile: the apps
// this controller offers for a person's own machines, each with its version
// beside the controller's, Download and how to connect it; and under them
// the devices signed in as you, with Disconnect. Its own classic script
// beside index.html, per the new-surface rule; chrome from docSurface().
//
// What is offered is the Settings page's (apps_* switches, apps.py); what
// is held is what the controller fetched from its release and checked. A
// person downloads from here, and an app that finds itself behind comes
// here, or fetches from /apps itself (the companion, R270 step 9).

"use strict";

let devApps = null, devAppsRev = 0;

function openDevicesTab(){
  openTab({kind: "devices", arg: "__devices", label: "Devices"});
}

// What the controller offers and holds (apps.view), for this page and the
// Controller page's Apps section.
async function loadApps(){
  try{
    const r = await bootFetch("/api/apps");
    const j = await r.json();
    if (!j.error) devApps = j;
  }catch(e){ /* each page says it could not read them */ }
  devAppsRev++;
  if (tabs.some(t => t.kind === "devices" || t.kind === "settings")) drawPanes();
}

async function loadDevicesPage(){
  await Promise.all([loadApps(), loadProfile()]);
}

// Each section's line on the list beside it.
const DEVICES_SAYS = {apps: "the apps to install, from this controller", mine: "the apps signed in as you"};

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
      <div class="name">${esc(a.title)}${a.version ? ` <span class="pill${behind ? " warn" : ""}">${esc(a.version)}</span>` : ""}</div>
      <div class="hint">${esc(a.does)}</div>
      ${first ? `<div class="sub">${devHow(a.name)}</div>`
        : `<div class="sub warn">Not fetched yet${devApps?.problem ? "" : ": the controller looks at its release a while after it starts, then daily"}.</div>`}
      ${rest.length ? `<div class="sub dim">Also: ${rest.map(f => `<a href="${esc(f.url)}" download>${esc(f.file)}</a>`).join(", ")}</div>` : ""}
    </div>
    <div class="actbar">${first ? `<a class="btn primary" href="${esc(first.url)}" download title="${esc(first.file)} · sha256 ${esc(first.sha256.slice(0, 12))}…">Download</a>`
      : `<button type="button" class="primary" disabled>Download</button>`}</div></div>`;
}

function renderDevicesInto(i){
  const d = docSurface(i, "devices");
  if (!d) return;
  if (!devApps || !profile){
    d.setBar(`<span class="barfacts">${skv(14)}</span>`);
    splitOff(d.list);
    d.list.innerHTML = skTpl(skSplit([["Apps", DEVICES_SAYS.apps], ["Signed in as you", DEVICES_SAYS.mine]],
                                     "Apps", skRows(3)));
    return;
  }
  const offered = (devApps.apps || []).filter(a => a.offered);
  const mine = profile.devices || [];
  d.setBar(`<span class="barfacts">controller ${esc(devApps.version || "unstamped")} · ${mine.length} device${mine.length === 1 ? "" : "s"}</span>`);
  d.list.innerHTML = docSection("devices", "apps", "Apps", String(offered.length || ""),
      offered.length ? (devApps.problem ? `<div class="field"><div class="notice warn">The controller's last look at its release did not work: ${
          esc(devApps.problem)}</div></div>` : "") + offered.map(devAppRow).join("")
        : `<div class="empty">This controller offers no apps: an administrator picks them on the Controller page, under Apps.</div>`)
    + docSection("devices", "mine", "Signed in as you", String(mine.length || ""), profileDevices(mine));
  wireSections(d.list);
  splitSects(d.list, "devices", {says: DEVICES_SAYS, back: "Devices"});
  wireDeviceOut(d.el);
}
