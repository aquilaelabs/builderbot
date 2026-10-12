"use strict";
// ---- first run: the setup page (R199) ---------------------------------------
//
// After the owner is made, the page is this until Finish: what the controller
// needs that lives in the app rather than the environment (where what grows
// is kept, when an idle Claude session ends, the public hostname), each with
// its default shown and nothing to change unless the default is wrong, and
// then a node, which cannot wait: nothing runs without one (the operator,
// 12 Oct). The node step is the Nodes tab itself under the panel, with its
// own Create sandbox VM and Enroll node, so there is one way to enroll and
// it is the one this page teaches. Finish is refused by the server too
// until a node is enrolled and answering.

let setupSig = "";

function setupNeeded(){
  return state?.settings?.settings?.setup_done?.value === false;
}

// A node enrolled and answering, from the Nodes tab's list.
function setupNode(){
  return (nodesList || []).find(n => n.kind === "agent" && n.state === "online" && n.live !== false) || null;
}

function drawSetup(){
  const on = setupNeeded();
  document.body.classList.toggle("firstrun", on);
  const el = $("setupPanel");
  if (!on){
    if (!el.hidden){ el.hidden = true; el.innerHTML = ""; setupSig = ""; }
    return;
  }
  el.hidden = false;
  // The Nodes tab in front, for the step that needs it.
  const nt = tabs.find(t => t.kind === "nodes");
  if (!nt) openNodesTab();
  else if (tabOf(panes[active])?.kind !== "nodes") focusTab(nt.id);
  const node = setupNode();
  // Drawn again only when what it shows has moved: a poll landing mid-type
  // would otherwise take what was typed with it.
  const sig = JSON.stringify([settingsLive(), node?.name || ""]);
  if (sig === setupSig) return;
  setupSig = sig;
  const tunnel = settingsSections().find(g => g.key === "tunnel");
  const step = (n, title, html, opt) => `<details class="sect" open><summary><span class="t">${n}. ${esc(title)}</span>${
    opt ? `<span class="state">optional</span>` : ""}</summary><div class="body">${html}</div></details>`;
  el.innerHTML = `<div class="setuphead">
      <h2>Set up BuilderBot</h2>
      <p class="dim">The first three have defaults, shown below; change one only if it is wrong for this machine, and each stays under Controller settings afterwards. The fourth cannot wait: BuilderBot works on nodes, so the rest opens once one is enrolled.</p>
    </div>
    ${pathsSection() ? step(1, "Where what grows is kept", pathsSection()) : ""}
    ${step(2, "When an idle Claude session ends", idleSection())}
    ${tunnel ? step(3, "A public hostname, for nodes off this network", tunnel.html, true) : ""}
    ${step(4, "Your first node", `<div class="row stack2"><div class="grow">
        <div class="${node ? "" : "dim"}">${node
          ? `${esc(node.name)} is enrolled and answering.`
          : "Create a sandbox VM, or enroll a machine you already have, with the two buttons on the Nodes tab below. Finish opens once it is enrolled and answering."}</div>
        <div class="actbar"><span class="sp"></span>
          <button type="button" class="primary" id="setupFinish"${node ? "" : " disabled"}>Finish</button></div>
        <div class="hint bad" id="setupWhy" hidden></div>
      </div></div>`)}`;
  wireIdleSection(el);
  wirePathsSection(el);
  wireSettingsSections(el);
  settingsKeep(el);
  $("setupFinish").onclick = setupFinish;
}

async function setupFinish(){
  const btn = $("setupFinish"), why = $("setupWhy");
  busy(btn, "Finishing");
  let j;
  try{
    j = await (await postJSON("/api/settings", {set: {setup_done: true}})).json();
  }catch{ j = {error: "no answer from the dashboard"}; }
  if (j.error){
    unbusy(btn, "Finish");
    why.textContent = j.error;
    why.hidden = false;
    return;
  }
  setupSig = "";
  refresh();
}
