// A Claude session, started: which of the project's nodes it runs on, what
// each node has, and whether it resumes a conversation or starts a fresh
// one, from the chooser the Claude button opens.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- a Claude session: which node, and resume or fresh ------------------

// Which project's resume chooser is open, if any.
let resumeFor = null;
// Which of a project's nodes a Claude press picked, per project, for the
// moment between the node stage of the chooser and the resume stage (R82).
let claudeNodePick = {};

// `ps -o etime=` gives MM:SS under an hour, HH:MM:SS under a day, and
// D-HH:MM:SS beyond one. Rendered raw in a header with four buttons beside it
// that is exactly what ran out of room on a phone, and it did not wrap or
// shrink, it ELLIPSISED, so "09:52:31" became "09:52:…", which reads as a
// perfectly good and completely different number. Two units is all anybody
// reads off a header anyway; the About popup keeps the precise one.
function shortUptime(raw){
  const t = String(raw || "").trim();
  const m = t.match(/^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$/);
  if (!m) return t;                       // "?" from a ps that would not answer
  const [d, h, mi, sec] = [+(m[1] || 0), +(m[2] || 0), +m[3], +m[4]];
  // Only where the third field exists is the first hours; without it ps is
  // counting minutes and seconds, and calling those hours would be a lie in
  // the direction nobody checks.
  const parts = m[2] === undefined
    ? [[mi, "m"], [sec, "s"]]
    : [[d, "d"], [h, "h"], [mi, "m"], [sec, "s"]];
  const shown = parts.filter(([n]) => n > 0).slice(0, 2);
  return shown.length ? shown.map(([n, u]) => n + u).join(" ") : "0s";
}

const ago = s => {
  const d = Math.max(0, Math.floor(Date.now()/1000) - s);
  return d < 90 ? "just now"
       : d < 5400 ? `${Math.round(d/60)} min ago`
       : d < 172800 ? `${Math.round(d/3600)} h ago`
       : `${Math.round(d/86400)} days ago`;
};

// A live session is simply resumed by attaching: its tab is the conversation.
// The choice only arises when nothing is running but a transcript survives,
// which is exactly what a container restart leaves behind.
function openClaude(name, ev){
  ev?.stopPropagation();
  const p = (state?.projects || []).find(x => x.name === name);
  // Several nodes to work on: which one comes first, then resume or new
  // (R82). One node asks nothing, as before.
  if ((p?.session_nodes || []).length > 1 && !claudeNodePick[name]){
    resumeFor = resumeFor === name ? null : name;
    drawProjects(state.projects);
    return;
  }
  if (p?.session_why && !liveSessions().has(myClaude(name))){
    // There is nowhere for it to run: the press opens the reason under the
    // row rather than a tab, which is the whole of what it can do.
    resumeFor = resumeFor === name ? null : name;
    drawProjects(state.projects);
    return;
  }
  if (liveSessions().has(myClaude(name)) || !p?.last_claude){
    resumeFor = null;
    return startClaude(name, null, claudeNodePick[name] || "");
  }
  resumeFor = resumeFor === name ? null : name;
  drawProjects(state.projects);
}

function startClaude(name, sessionId, node){
  resumeFor = null;
  delete claudeNodePick[name];
  // Redraw the card, not just the tabs: the chooser is a child of it and would
  // otherwise sit there until the next poll, over a choice already made.
  if (state) drawProjects(state.projects);
  const p = (state?.projects || []).find(x => x.name === name);
  const nn = node ? (p?.session_nodes || []).find(x => x.id === node)?.name || node : "";
  openTab({kind:"term",
           arg: `claude:${name}` + (sessionId ? `:r:${sessionId}` : "") + (node ? `:n:${node}` : ""),
           label: `Claude: ${name}` + (nn ? ` (${nn})` : "")});
}

// What a node has and how busy it is, on its button in the chooser: the
// pick is a read (a card for the emulator, a quiet box), not a name.
function claudeNodeFacts(n){
  const s = n.sample || {};
  const bits = [];
  if (s.cpu_pct !== undefined) bits.push(`cpu ${s.cpu_pct}%`);
  if (s.mem_mb) bits.push(`${Math.round((s.mem_used_mb || 0) / 1024 * 10) / 10}/${Math.round(s.mem_mb / 1024)}GB`);
  if (n.gpu) bits.push(n.gpu);
  if ((n.tools || []).length) bits.push(n.tools.join(", "));
  return bits.join(" · ");
}

function placeResumeMenu(){
  const p = (state?.projects || []).find(x => x.name === resumeFor);
  const anchor = $("projects").querySelector(`[data-c="${CSS.escape(resumeFor)}"]`);
  const nodeStage = (p?.session_nodes || []).length > 1 && !claudeNodePick[p.name];
  if ((!p?.last_claude && !p?.session_why && !nodeStage) || !anchor){ resumeFor = null; return; }
  const card = anchor.closest(".card");
  const m = document.createElement("div");
  m.className = "pinmenu resumemenu";
  m.id = "resumemenu";
  // The node first, when there are several (R82): a button per node with
  // what it has, dead with its reason where a session cannot start there.
  m.innerHTML = nodeStage
    ? `<div class="sub">Which node?</div>` + p.session_nodes.map(n =>
        `<button data-node="${esc(n.id)}"${n.where === "node" ? "" : " disabled"} title="${
          esc(n.where === "node" ? "" : n.why)}">${esc(n.name)}${
          claudeNodeFacts(n) ? ` <span class="dim">${esc(claudeNodeFacts(n))}</span>` : ""}</button>${
          n.where === "node" ? "" : `<div class="sub bad">${esc(shortWhy(n.why))}</div>`}`).join("")
    : p.session_why
    // No node, or one that refused, and there is nowhere else: a session
    // runs on a node and this container carries no Claude Code. The reason,
    // and no choice under it: a menu with nothing in it would be a button
    // that lies.
    ? `<div class="sub">${esc(p.session_why)}</div>`
    : `<button data-r="1">Resume: ${esc(ago(p.last_claude.when))}</button>` +
      `<button data-n="1">New conversation</button>`;
  card.appendChild(m);
  m.querySelectorAll("[data-node]").forEach(b => b.onclick = () => {
    claudeNodePick[p.name] = b.dataset.node;
    // Straight on when there is nothing to resume; else the second stage.
    if (!p.last_claude || liveSessions().has(myClaude(p.name))) return startClaude(p.name, null, b.dataset.node);
    drawProjects(state.projects);
  });
  const a = anchor.getBoundingClientRect(), c = card.getBoundingClientRect();
  m.style.left = Math.max(4, Math.min(a.left - c.left, c.width - m.offsetWidth - 4)) + "px";
  m.style.top = (a.bottom - c.top + 4) + "px";
  m.querySelector("[data-r]") && (m.querySelector("[data-r]").onclick = () => startClaude(p.name, p.last_claude.id, claudeNodePick[p.name] || ""));
  m.querySelector("[data-n]") && (m.querySelector("[data-n]").onclick = () => startClaude(p.name, null, claudeNodePick[p.name] || ""));
  // ...and brought into the sidebar, which scrolls. Pressing Claude on a
  // project whose session has ENDED opens this chooser instead of a tab;
  // that is the design, and it is the only thing the press does, so a
  // chooser placed below the fold is a press with no visible result. Reported
  // as "opened Claude again and it did not go to the new tab" (bug #65).
  // Same rule and the same fix as the notebook's view strip: arriving
  // somewhere you cannot see reads as nothing having happened.
  //
  // Measured at rest. scrollIntoView reads the box where it is, and where it
  // is right now is menuIn's first frame, 5px above where it will settle,
  // so aligning that box left the settled chooser 5px below the fold (B77).
  // Finish the entrance for the measurement and play it again from the start.
  const enter = m.getAnimations()[0];
  enter?.finish();
  m.scrollIntoView({block: "nearest", inline: "nearest"});
  enter?.play();
}
