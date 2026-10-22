// The page's state, and the helpers every other script reaches for: the
// tab strip and the panes, the status poll's answer (`state`, the one
// source), `$` and `esc`, a field's label and its help, one POST for
// everything the page sends, what a session is called and whose it is, and
// how a time or a size is written.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- state -----------------------------------------------------------

// The workspace tab is only the default the page starts with, not a fixture:
// every tab can be minimized, and killing a session from the Sessions card
// takes its tab with it: the workspace one included, which used to be
// unclosable and so sat pointing at a dead session. An empty strip is legal;
// the pane renders a placeholder and "+" starts over. Tabs are separate from
// panes on purpose: a pane is a viewport, and closing one should not destroy
// what it was showing.
// A new layout opens on the projects, with the controller's shell beside
// them: the shell first was a raw prompt for a newcomer, and on a setup
// whose work runs on nodes, one that could not even start (R119, 4 Oct).
let tabs = [{id:"pj", kind:"projects", arg:"__projects", label:"Projects"},
            {id:"ws", kind:"term", arg:"shell", label:"sh: workspace"}];
// The windows terminals were popped out into (R8), by tab id: this browser's
// own handles, which is the only way a page can know a popped window still
// lives. A reload loses them, and a tab popped from a page since reloaded
// comes back into the strip: the edge R8 named, decided this way.
const popWins = new Map();
let panes = ["pj", null];
// What a session's container ask is asking for, from its own command line:
// "new" makes a container, "remove" removes one, "env set" writes its env,
// start, stop and restart are themselves, and only the rest is a rebuild.
// The card said rebuild for all of them (B301).
function askVerb(a){
  return a.ctl || ({new: "create", remove: "remove", env: "env set"}[a.cmd?.[1]] || "rebuild");
}
let active = 0;
let state = null;   // the status poll's answer, and the one source: a `let` that
                    // mirrors part of it drifts (B213, B215), so read it here
let findings = null;
// Shut, on every device. A touch device is where the on-screen keys are most
// useful and also where they cost the most room: opening one over the
// terminal before anybody asked meant arriving at a phone with half the
// screen already spent. The ⌨ button is right there.
let showKeys = false;
let seq = 0;

const $ = id => document.getElementById(id);
// A field's label sits above it, and what the label cannot say rides a ?
// beside it (docs/design-language.md, Controls). `id` may be "" for a
// label that names a group rather than one control.
// The words a title carried, now that untitle() keeps them for a screen
// reader rather than a tooltip: what a control is described or named by.
const saidOf = el => el ? (el.getAttribute("aria-description") || el.getAttribute("aria-label") || el.getAttribute("title") || "") : "";
const helpIcon = t => t ? `<span class="help" data-help="${esc(t)}" aria-label="${esc(t)}" role="button" aria-expanded="false" tabindex="0">?</span>` : "";
const lbl = (id, text, help) => `<label class="lbl"${id ? ` for="${esc(id)}"` : ""}>${esc(text)}${helpIcon(help)}</label>`;
// One POST for everything the page sends: JSON in, the Response back, so
// the caller reads r.ok and r.json() as it always did. Written once here
// after forty-eight copies of the same three headers (R60).
function postJSON(path, body){
  return fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
                      body: JSON.stringify(body)});
}

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const tabOf = id => tabs.find(t => t.id === id) || null;
const isSplit = () => panes[1] !== null;

// ---- what a session is called, and whose it is --------------------------

// Mirrors bb-tty. The key bar, the kill button and the macro sender all address
// tmux by name, and the terminal is an iframe we cannot reach into, so they
// must agree. A resumed conversation is the same session as a fresh one: the
// suffix chooses what claude starts with, not which tmux session it lands in.
//
// tmux rewrites `.` and `:` in a session name to `_` without saying so, and
// bb-tty makes the same substitution on purpose (see start() there), so a
// project called `example.com` runs as `claude-example_com`. Every name
// derived from a project name here goes through tmuxName(), or the kill,
// keys and macro requests would name a session that never existed.
const tmuxName = s => s.replace(/[.:]/g, "_");
// Whose shell this is (roadmap #26). A SHELL is named for its account, because
// two people opening a terminal on one project must otherwise land in the same
// one: tmux attaches to an existing session rather than making a second. A
// CLAUDE session is not: one conversation per project is the rule, and who
// holds it is a record rather than a name.
//
// The prefix comes from the server rather than being built here, because the
// OWNER has none; they keep the bare names, the way they keep /home/builder
//, and a page that derived the rule for itself would be a fourth copy of it
// to keep in step. bb-tty's sess() is the other half; `~` is the separator
// because tmux rewrites `.` and `:` and leaves this alone.
const myTmux = s => (state?.tmux_prefix || "") + s;
// The account holding this project's Claude session, when it is not us. The
// button grays and wears their name; the refusal itself is at the /term proxy,
// because a rule only the page honors is a suggestion (roadmap #26).
// A project this account can see and has not taken on (roadmap #27). An
// administrator is shown every project: hiding one from somebody who
// administers the box only sends them looking for it, and works on the ones
// on their own list. Read-only here means the controls that change something
// are off and the server refuses them; it is a seatbelt against editing the
// wrong project, not a wall, because an administrator has a shell.
const notMine = p => p.mine === false;
const NOT_MINE_WHY = "read-only: you hold no role on this project; its owner or an "
  + "administrator gives you one to work on it";
// Why this account may not change a project, or "" (B86): not taken on, or
// a role that gives Projects Read and not Write, as the server words it on
// the row (write_why). Every writing control on the project's page is dead
// on it, with this under it in red; the server refuses the same.
const writeWhy = p => !p ? "" : notMine(p) ? NOT_MINE_WHY : (p.write_why || "");
const projWriteWhy = name => writeWhy((state?.projects || []).find(p => p.name === name));
// ...and why its version is not this account's to move or release, or ""
// (B101): Releases and versions Write, which Projects Write does not carry.
const projReleaseWhy = name => {
  const p = (state?.projects || []).find(x => x.name === name);
  return !p ? "" : notMine(p) ? NOT_MINE_WHY : (p.release_why || "");
};
// The reason under a dead control, a feature this install switched off: one
// line in the warning's yellow, since a control that is off is not an error
// (the operator, 21 Oct). A role an account lacks is never one: what it does
// not give is not drawn at all.
const deadWhy = why => why ? `<div class="notice warn deadwhy">${esc(why)}</div>` : "";
// A feature this install switched off (R81): its sentence, or "" when it is
// on. Every control the feature draws is dead with this under it.
const featureOff = feature => state?.off?.[feature] || "";
// May this account have a shell at all (roadmap #27)? An account without one
// gets its Claude session as a read-only console: the proxy relays it to a
// ttyd started without --writable and refuses any argument that is not a
// Claude session on a project they were given. This only decides what is
// DRAWN; every one of these is refused again on the server.
const mayShell = () => state?.can?.terminal !== false;
const mayDocker = () => state?.can?.["docker-write"] !== false;
// ...on that node where one is named (R260: Toolchains held node by node),
// read off the node's row; a node not drawn yet is the server's to refuse.
const mayToolchains = nid => state?.can?.["toolchains-write"] !== false
  && (!nid || ((typeof nodesList === "undefined" ? null : nodesList)?.find(x => x.id === nid)?.areas_may?.toolchains ?? "write") === "write");
// THIS account's Claude session on a project. Prefixed like a shell since
// roadmap #24: more than one person may work a project at once, each in a
// worktree of their own, so the name has to say whose conversation it is,
// and the name is then the only record of that, with no file to go stale.
// Every "is it running" question below is about the asker's own.
// Which agent's session it is, the agent table says (R95): Claude's here.
const myAgentSession = (id, proj) => myTmux(tmuxName((agentById(id) || AGENTS[0]).id + "-" + proj));
const myClaude = proj => myAgentSession("claude", proj);
// A name with somebody's prefix taken off, for the questions that are about
// the session rather than about whose it is.
const tmuxBase = s => String(s).replace(/^u_[0-9a-f]{8}~/, "");
function sessionOf(arg){
  if (arg.startsWith("sh:")){
    const [, n, proj] = arg.split(":");
    return myTmux(tmuxName(proj ? `shell-${proj}-${n}` : `shell-${n}`));
  }
  const ag = agentOfArg(arg);
  if (ag) return myAgentSession(ag.agent.id, ag.project);
  if (arg.startsWith("shell:"))  return myTmux(tmuxName("shell-"  + arg.slice(6)));
  // ctr:NAME:INSTANCE:CONTAINER, named by its container (bb-tty's ctr-).
  if (arg.startsWith("ctr:"))    return myTmux(tmuxName("ctr-" + arg.split(":")[3]));
  // vm:PROJECT:NAME, a VM's console (R91), named by its domain (bb-tty's vm-).
  if (arg.startsWith("vm:"))     return myTmux(tmuxName("vm-bbvm-" + arg.split(":")[1].toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24) + "-" + arg.split(":")[2]));
  return arg;
}
// The project a session name was made from, when it is one we know: the
// tmux name is not always the project name (see tmuxName), so labels and
// reopen-by-name look it up rather than slicing the prefix off.
const projFor = n =>
  (state?.projects || []).find(p => tmuxName(p.name) === n)?.name ?? null;

const isClaude = t => t.kind === "term" && !!agentOfSession(tmuxBase(sessionOf(t.arg)));
const liveSessions = () => new Set((state?.sessions || []).map(s => s.name));
// Named from the session rather than the tab: a Claude session with no tab
// is still a conversation.
const claudeSessions = () => [...liveSessions()].filter(n => agentOfSession(n));

// What a Claude session is doing ({state: "working"|"waiting", task}) read
// from the pane title the server collected, or null for anything else. The
// distinction the badge carries is the phone-glance question: is it still
// going, or is it sitting there needing me?
const claudeOf = name =>
  (state?.sessions || []).find(s => s.name === name)?.claude || null;

const stateDot = c => c
  ? `<span class="st ${c.state}" title="${c.state === "working" ? "working"
      : c.state === "asking" ? "asking you to approve something in its terminal" : "waiting for you"}"></span>` : "";

// ---- times and sizes ----------------------------------------------------

// The time zone this browser shows times in, chosen on the Profile tab and
// kept in a cookie: it is where this device is, not who the account is, so a
// phone abroad and the desk at home each keep their own. "" is the device's
// own zone, which is what the browser does unasked. A zone the browser does
// not know is ignored rather than trusted.
const TZ_COOKIE = "bb_tz";
function userTZ(){
  const m = document.cookie.match(/(?:^|;\s*)bb_tz=([^;]*)/);
  const z = m ? decodeURIComponent(m[1]) : "";
  if (!z) return "";
  try{ new Intl.DateTimeFormat([], {timeZone: z}); return z; }catch(e){ return ""; }
}
function setUserTZ(z){
  document.cookie = `${TZ_COOKIE}=${encodeURIComponent(z || "")}; path=/; SameSite=Lax; `
    + (z ? "max-age=315360000" : "max-age=0");
}
// Every time the page shows goes through here: `t` in milliseconds.
function fmtTime(t, opts = {}){
  const z = userTZ();
  return new Date(t).toLocaleString([], z ? {...opts, timeZone: z} : opts);
}

// ...and GB past a gigabyte (B825): a 19 GB limit read 19476.5MB.
const humanBytes = n =>
  n >= 1073741824 ? (n / 1073741824).toFixed(1) + "GB"
  : n >= 1048576 ? (n / 1048576).toFixed(1) + "MB"
  : n >= 1024 ? Math.round(n / 1024) + "kB" : (n || 0) + "B";

// ---- fields a password manager leaves alone ------------------------------
// Bitwarden offered itself on every text box on the page (B495): a search,
// a note, a role's purpose. It ignores autocomplete="off" and honors only
// its own attribute, as 1Password and LastPass honor theirs, so every field
// that is not a password or a sign-in carries all three. A password field,
// and one whose autocomplete names an account or a password, is left as it
// is: those are where a manager belongs. Wired in index.html on every
// element that appears, the way proselines are; idempotent.
const MANAGER_FIELDS = new Set(["username", "current-password", "new-password", "one-time-code", "email"]);
function quietFields(root){
  const all = root.matches?.("input, textarea") ? [root] : [];
  for (const el of [...all, ...(root.querySelectorAll?.("input, textarea") || [])]){
    if (el.dataset.bwignore !== undefined) continue;
    const t = (el.getAttribute("type") || "text").toLowerCase();
    if (t === "password" || t === "hidden" || t === "checkbox" || t === "radio" || t === "file") continue;
    if (MANAGER_FIELDS.has((el.getAttribute("autocomplete") || "").toLowerCase())) continue;
    el.setAttribute("data-bwignore", "");
    el.setAttribute("data-1p-ignore", "");
    el.setAttribute("data-lpignore", "true");
  }
}
