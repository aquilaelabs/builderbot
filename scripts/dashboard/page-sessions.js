// The Sessions page: every terminal and Claude session this account has,
// the tab each is in, and ending one.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- the sessions page --------------------------------------------------

// A session tmux knows as "claude-Foo" is the same thing the Projects card
// opens as "claude:Foo". Opening it under the raw name takes bb-tty's fallback
// branch: a bare shell at /workspace, skipping the project directory, the
// exclusion check and the scoped settings, which is only invisible while the
// session already exists. Map it back when the project is one we know.
function argForSession(name){
  // Whoever owns it, the arg is derived from what comes AFTER the prefix;
  // that part is the project and the number, which is all bb-tty is told.
  // The listing only carries sessions this account may see, so a prefixed one
  // here is this account's own and sessionOf puts the prefix back.
  name = name.replace(/^u_[0-9a-f]{8}~/, "");
  // Matched through tmuxName (a session's name is the project's with `.` and
  // `:` rewritten), and by exact project first, so a project genuinely called
  // "web-2" is not read as terminal 2 of a project called "web".
  for (const [prefix, arg] of [...agentsLive().map(a => [a.id + "-", a.id + ":"]), ["shell-", "shell:"]]){
    const p = name.startsWith(prefix) ? projFor(name.slice(prefix.length)) : null;
    if (p) return arg + p;
  }
  // shell-<project>-<n> and shell-<n>, the numbered terminals.
  const m = /^shell-(?:(.+)-)?(\d+)$/.exec(name);
  if (m){
    const p = m[1] ? projFor(m[1]) : "";
    if (p !== null) return `sh:${m[2]}:${p}`;
  }
  return name;
}

function openSessionsTab(){
  openTab({kind: "sessions", arg: "__sessions", label: "Sessions"});
}

// The project a session belongs to, read the way its tab's argument is:
// "" for a terminal at the workspace.
function sessionProject(name){
  const m = /^(?:claude|shell):(.+)$/.exec(argForSession(name)) || /^sh:\d+:(.*)$/.exec(argForSession(name));
  return m ? m[1] : "";
}

// The Sessions page (R250 step 1, the design's tables rule): every terminal
// and Claude session of this account, here and on the nodes, one row each.
// The name opens its tab; Open puts a tab back, Minimize takes a shell's off
// the strip (it keeps running), and End stops one, which closing a tab never
// does. It reads the status poll's sessions, so it draws on every read and
// paints only what changed.
const SESS_COLS = [{label: "Session"}, {label: "Project", w: "minmax(0,.7fr)"}, {label: "Node", w: "minmax(0,.6fr)"},
                   {label: "Started", w: "7rem"}, {label: "", act: true, w: "10.5rem"}];

function renderSessionsInto(i){
  const d = docSurface(i, "sessions");
  if (!d) return;
  const ss = state?.sessions;
  if (!ss){
    d.setBar(`<span class="dim">${skv(6)}</span>`);
    paint(d.list, skTpl(skTable(SESS_COLS, 3, "sesstbl", "row sessrow")));
    return;
  }
  const agentSs = ss.filter(s => agentOfSession(tmuxBase(s.name))), claudes = agentSs.length;
  d.setBar(`<span class="dim">${ss.length} session${ss.length === 1 ? "" : "s"}${
    claudes ? `, ${claudes} of them ${agentsWord(agentSs.map(s => s.name))}` : ""}</span>`);
  // Named exactly as its tab is: the tmux name and the full path are in the
  // name's description, where the detail belongs.
  const names = sessionLabels();
  const tabFor = new Map(tabs.filter(t => t.kind === "term").map(t => [sessionOf(t.arg), t]));
  const rows = ss.map(s => {
    const t = tabFor.get(s.name);
    const claude = !!agentOfSession(tmuxBase(s.name));
    const tip = tabTitle(t || {kind: "term", arg: argForSession(s.name), label: s.name});
    const proj = sessionProject(s.name);
    // Only while it IS working: the task comes off the pane title, which
    // Claude sets as it goes and never clears, so an idle session would
    // keep showing the last thing it happened to be doing.
    const task = s.claude?.task && s.claude.state === "working"
      ? `<div class="sub" title="${esc(s.claude.task)}">working on: ${esc(s.claude.task)}</div>` : "";
    return `<div class="row sessrow" data-sess="${esc(s.name)}">${tblLine(SESS_COLS, [
      `<span class="name go" data-go="${esc(s.name)}" title="${esc(tip)}">${stateDot(s.claude)}${
        esc(names.get(s.name) || s.name)}</span>${t && panes.indexOf(t.id) !== -1 ? ` <span class="pill ok">on screen</span>` : ""}${task}`,
      proj ? esc(projLabel(proj)) : `<span class="dim">workspace</span>`,
      s.node ? esc(s.node) : `<span class="dim">this controller</span>`,
      s.created ? esc(ago(s.created)) : "",
      `<div class="actbar">${t ? (claude ? "" : `<button type="button" data-min="${esc(t.id)}"
          title="take its tab off the strip; it keeps running">Minimize</button>`)
        : `<button type="button" data-a="${esc(s.name)}" title="reopen its tab">Open</button>`}
        <button type="button" class="danger" data-k="${esc(s.name)}" data-kn="${esc(s.node_id || "")}"
          title="${claude ? "end this Claude session: the transcript is kept" : "end this session and what runs in it"}">End</button></div>`])}</div>`;
  }).join("");
  const html = ss.length ? tblWrap(SESS_COLS, rows, "sesstbl")
    : `<div class="hint">nothing is running: a terminal or a Claude session you open is listed here</div>`;
  if (!paint(d.list, html)) return;
  // Kept from the pane under the page: its click makes the page's pane the
  // active one, and the terminal just opened in the dock would lose the
  // keys and the commands to a page that cannot take them.
  const goTo = (e, name) => { e.stopPropagation(); openTab({kind: "term", arg: argForSession(name), label: name}); };
  d.list.querySelectorAll("[data-a]").forEach(b => b.onclick = e => goTo(e, b.dataset.a));
  d.list.querySelectorAll("[data-go]").forEach(n => n.onclick = e => goTo(e, n.dataset.go));
  d.list.querySelectorAll("[data-min]").forEach(b => b.onclick = () => hideTab(b.dataset.min));
  d.list.querySelectorAll("[data-k]").forEach(b => b.onclick = () => killSession(b.dataset.k, b.dataset.kn));
}

// `node` is the id of the node the session runs on, when the row said so:
// the same name can exist here and there: a project unbound from a node
// while a session was still open on it, and the row knows which it meant.
async function killSession(name, node = ""){
  const ag = agentOfSession(tmuxBase(name)), claude = !!ag;
  // Named as its row and its tab are, never by its tmux name (B58).
  const proj = sessionProject(name);
  const said = claude ? `the ${ag.agent.name} session on ${proj ? projLabel(proj) : name}`
    : `the session "${sessionLabels().get(name) || name}"`;
  if (!await askYes(claude
        ? `End ${said}?\n\nThe transcript is kept and can be `
          + `resumed later, but the conversation stops now.`
        : `End ${said}?\n\nAnything running in it is terminated.`)) return;
  try{
    const j = await endSession(name, node);
    if (j.error){ notify(j.error, true); return; }
    // Its tab, if one is open, is now pointing at nothing.
    const t = tabs.find(x => x.kind === "term" && sessionOf(x.arg) === name);
    if (t) dropTab(t.id);
    notify(`ended ${said}`);
  }catch(e){ notify("could not end it: " + e, true); }
  await refresh();
  // Nowhere near another End (B54): with focus left on the list, a keyboard
  // Enter after the redraw could end a second session.
  const a = document.activeElement;
  if (a?.matches?.("[data-k], .consend")) a.blur();
}

// End a session, no questions asked. killSession is this with the dialog in
// front of it.
async function endSession(name, node = ""){
  const r = await postJSON("/api/session", {action:"kill", session:name, node});
  return r.json();
}

// ---- who has a session on a project ----
// Who else has a conversation open on this project. Not a refusal any more
// (roadmap #24): they each work in a tree of their own, so the row says who is
// here rather than taking the button away. What IS refused is a second session
// on one Anthropic account, and that refusal comes from the server when the
// terminal is opened, in its own words.
// Keyed by the tmux-safe name (claude_with comes off the session names),
// so a project with a dot in its name is looked up by that: by its own
// name its row said nobody was here while a session ran (29 Sep).
const withMe = p => (state?.claude_with || {})[tmuxName(p)] || (state?.claude_with || {})[p] || [];
// The others, for the places that are about somebody else being here.
const othersOn = p => withMe(p).filter(n => n !== state?.me);
// Who has a conversation open here, one line each with a dot in front:
// bright while that session is working on a prompt, dim while it waits (the
// operator, 24 Sep, in place of one sentence naming them all). BuilderBot
// account names, not the Anthropic logins behind them: whose session it is
// on this box is the question somebody looking at the row is asking. Your
// own is last and says so, so the other people, the part that is news, come
// first.
// The two maps behind those rows, fetched on their own when the revs token
// `live` moves: a session starting, ending or turning to work shows within
// a few seconds, where the status poll runs git for every project and
// stays at fifteen (the operator, 25 Sep).
async function liveRefresh(){
  let j;
  try{ j = await (await fetch("/api/live")).json(); }catch(e){ return; }
  if (!state || !j || j.error) return;
  // Your own sessions starting or ending are what the cards' Open Claude,
  // a project's header and its settings read off the status read's session
  // list, which this light read does not carry and keeps putting off: so a
  // change in yours reads it at once (the operator, 17 Oct: Start agent
  // stayed until a reload).
  const yours = w => Object.entries(w || {}).filter(([, ns]) => (ns || []).includes(state.me)).map(([k]) => k).sort().join(",");
  const moved = yours(j.claude_with) !== yours(state.claude_with);
  state.claude_with = j.claude_with || {};
  state.claude_busy = j.claude_busy || {};
  state.claude_asking = j.claude_asking || {};
  state.claude_where = j.claude_where || {};
  drawProjects(state.projects);
  if (moved) refresh();
}
function sessionRows(proj){
  const all = withMe(proj);
  if (!all.length) return "";
  const busy = new Set((state?.claude_busy || {})[proj] || []);
  const asks = new Set((state?.claude_asking || {})[proj] || []);
  const names = [...all].sort((a, b) => (a === state?.me) - (b === state?.me));
  // The session dot, the same one the session's tab, the phone's Terminal
  // tab and the Sessions card wear (stateDot's rule): working pulses in
  // the note color, waiting is the warn color. The row had a dot of its
  // own in other colors, and the same state read differently in each
  // place (the operator, 29 Sep).
  // One line per account per node, the node in brackets, so a person with
  // a session on two machines is two lines and each says whether it is
  // working there (the operator, 30 Sep). Where the payload has no node
  // rows (a session on this container), one line per account, as before.
  const where = (state?.claude_where || {})[tmuxName(proj)] || (state?.claude_where || {})[proj] || [];
  // ...and only while it names the same people as the map beside it, which
  // is the one a poll that has not carried it yet still fills.
  const whos = new Set(where.map(r => r.who));
  const agrees = where.length && names.every(n => whos.has(n)) && [...whos].every(w => names.includes(w));
  const rows = agrees
    ? [...where].sort((a, b) => (a.who === state?.me) - (b.who === state?.me) || a.node.localeCompare(b.node))
    : names.map(n => ({who: n, node: "", working: busy.has(n), asking: asks.has(n)}));
  // What changed since a session started that it does not see until it is
  // started again, said under it with what for (the operator, 12 Oct): a
  // toolchain put on its node's PATH, BuilderBot updated.
  // On Claude Code's permission prompt it is asking, whoever's it is (B104).
  return rows.map(r => `<div class="sessone"><span class="st ${r.asking ? "asking" : r.working ? "working" : "waiting"}" title="${
    r.asking ? "asking to approve something in its terminal" : r.working ? "working on a prompt" : "waiting for a prompt"}"></span>${esc(r.who)}${
    r.who === state?.me ? " (you)" : ""}${r.node ? ` <span class="dim">(${esc(r.node)})</span>` : ""}</div>${
    (r.behind || []).length ? `<div class="sessbehind">Restart ${r.who === state?.me ? "your session" : "this session"} to use what changed: ${
      esc(r.behind.join("; "))}.</div>` : ""}`).join("");
}
