// The Sessions card: every terminal and Claude session this account has,
// the tab each is in, and ending one.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- the sessions card --------------------------------------------------

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
  for (const [prefix, arg] of [["claude-", "claude:"], ["shell-", "shell:"]]){
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

function drawSessions(ss){
  const el = $("sessions");
  if (!ss.length){ paint(el, '<div class="empty">no tmux sessions; nothing is running</div>'); return; }
  // Named exactly as its tab is: the tmux name and the full path are on hover,
  // where the detail belongs.
  const names = sessionLabels();
  // The name is the way to a session's tab: click it and you are there,
  // reopened first if it was minimized. The button beside it does the other
  // thing: green when the tab is on the strip, and then it puts the tab away
  // (Minimize for a shell; Close for a Claude session, which asks first, the
  // way the ✕ does, because that one ends the conversation); plain "Open"
  // when there is no tab. The pill says whether the session is on screen
  // right now (in the dock: R218 step 4 took the split and its sides).
  const tabFor = new Map(tabs.filter(t => t.kind === "term").map(t => [sessionOf(t.arg), t]));
  const fresh = paint(el, ss.map(s => {
    const t = tabFor.get(s.name);
    const claude = tmuxBase(s.name).startsWith("claude-");
    const shownAt = t ? panes.indexOf(t.id) : -1;
    // A session on a node says so (roadmap #24): it is in that machine's
    // tmux, reached through the same tab, ended through its agent.
    const pill = (shownAt === -1 ? ""
      : `<span class="pill ok att">attached</span>`)
      + (s.node ? ` <span class="pill" title="runs on the node ${esc(s.node)}">on ${esc(s.node)}</span>` : "");
    const tip = tabTitle(t || {kind:"term", arg: argForSession(s.name), label: s.name});
    return `
    <div class="row">
      <div class="grow"><span class="name go" data-go="${esc(s.name)}" title="${esc(tip)}"
        >${stateDot(s.claude)}${esc(names.get(s.name) || s.name)}</span> ${pill}
        ${s.claude?.task && s.claude.state === "working"
          // Only while it IS working. The task comes off the pane title, which
          // Claude sets as it goes and never clears, so an idle session kept
          // showing the last thing it happened to be doing, with no age on it
          // and nothing to make it expire. "done: Nvidia EGL display error"
          // reads as a status and is a fossil. A session that is not doing
          // anything has no answer to "what is it doing", and the honest
          // version of that is a blank line rather than an old one.
          ? `<div class="sub" title="${esc(s.claude.task)}">working on: ${
              esc(s.claude.task)}</div>` : ""}</div>
      ${t ? (claude
          ? `<button class="primary" data-k="${esc(s.name)}" data-kn="${esc(s.node_id || "")}" title="end this Claude session: asks first">Close</button>`
          : `<button class="primary" data-min="${esc(t.id)}" title="take its tab off the strip; it keeps running">Minimize</button>`)
          : `<button data-a="${esc(s.name)}" title="reopen its tab">Open</button>`}
      <button data-k="${esc(s.name)}" data-kn="${esc(s.node_id || "")}" title="end this session">✕</button>
    </div>`; }).join(""));
  if (!fresh) return;
  // On a phone the list is a flyout over the terminal, and picking a session
  // is a request to look at it: the flyout gets out of the way.
  const goTo = name => { if (isPhone()){ showSessions = false; drawKeys(); }   // even if the
                         openTab({kind:"term", arg:argForSession(name), label:name}); };  // tab cap refuses
  el.querySelectorAll("[data-a]").forEach(b => b.onclick = () => goTo(b.dataset.a));
  el.querySelectorAll("[data-go]").forEach(n => n.onclick = () => goTo(n.dataset.go));
  el.querySelectorAll("[data-min]").forEach(b => b.onclick = () => hideTab(b.dataset.min));
  // Closing a terminal tab leaves its session running, so this is where one
  // actually gets ended: otherwise they would only ever accumulate.
  el.querySelectorAll("[data-k]").forEach(b => b.onclick = () => killSession(b.dataset.k, b.dataset.kn));
}

// `node` is the id of the node the session runs on, when the row said so:
// the same name can exist here and there: a project unbound from a node
// while a session was still open on it, and the row knows which it meant.
async function killSession(name, node = ""){
  const claude = tmuxBase(name).startsWith("claude-");
  if (!confirm(claude
        ? `End the Claude session "${name}"?\n\nThe transcript is kept and can be `
          + `resumed later, but the conversation stops now.`
        : `End the session "${name}"?\n\nAnything running in it is terminated.`)) return;
  try{
    const j = await endSession(name, node);
    if (j.error){ notify(j.error, true); return; }
    // Its tab, if one is open, is now pointing at nothing.
    const t = tabs.find(x => x.kind === "term" && sessionOf(x.arg) === name);
    if (t) dropTab(t.id);
    notify(`ended ${name}`);
  }catch(e){ notify("could not end it: " + e, true); }
  refresh();
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
  state.claude_with = j.claude_with || {};
  state.claude_busy = j.claude_busy || {};
  state.claude_where = j.claude_where || {};
  drawProjects(state.projects);
}
function sessionRows(proj){
  const all = withMe(proj);
  if (!all.length) return "";
  const busy = new Set((state?.claude_busy || {})[proj] || []);
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
    : names.map(n => ({who: n, node: "", working: busy.has(n)}));
  // What changed since a session started that it does not see until it is
  // started again, said under it with what for (the operator, 12 Oct): a
  // toolchain put on its node's PATH, BuilderBot updated.
  return rows.map(r => `<div class="sessone"><span class="st ${r.working ? "working" : "waiting"}" title="${
    r.working ? "working on a prompt" : "waiting for a prompt"}"></span>${esc(r.who)}${
    r.who === state?.me ? " (you)" : ""}${r.node ? ` <span class="dim">(${esc(r.node)})</span>` : ""}</div>${
    (r.behind || []).length ? `<div class="sessbehind">Restart ${r.who === state?.me ? "your session" : "this session"} to use what changed: ${
      esc(r.behind.join("; "))}.</div>` : ""}`).join("");
}
