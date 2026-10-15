// The two polls: refresh() fetches /api/status and draws from it, the one
// source of state, and pollRevs() asks every second and a half which
// revision tokens moved, onRev() being how a view says what to fetch when
// one does.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- the status poll ----------------------------------------------------

let bootSeen = null;                      // which run of the container this page saw
let preStatusUsed = false;                // the head's early fetch: once only

// Terminal tabs whose session we have actually watched running.
//
// The transition is what closes a tab, not the absence: "no session" is also
// true of a tab restored from a saved layout before anything has started, and
// of every tab for a moment if a poll ever comes back empty. Seen-then-gone
// happens exactly once, when the thing at the other end ended.
const seenLive = new Set();

// Close a terminal tab when its session has gone.
//
// bb-tty execs claude, so the pane's process IS the conversation: exit it:
// Ctrl+C twice, /exit, Ctrl+D, or a crash, and the pane dies, the tmux
// session goes with it, and the tab was left holding a dead terminal until
// somebody pressed ✕ on it. Nothing is lost by closing it: the transcript is
// on disk and the project's Claude button offers to resume it, which is a
// better way back than a corpse in a tab, because the row knows the id.
//
// Shells too, and for the same reason: a shell you typed `exit` in is just as
// dead, and one rule for terminal tabs is simpler than a carve-out.
function reapDeadTerminals(){
  const live = liveSessions();
  const gone = [];
  for (const t of tabs){
    if (t.kind !== "term") continue;
    const s = sessionOf(t.arg);
    if (live.has(s)) seenLive.add(s);
    else if (seenLive.has(s)){ seenLive.delete(s); gone.push(t.id); }
  }
  // Collected first: dropTab re-renders and repairs the panes, and doing that
  // while walking the list it edits is how one of two dying tabs gets missed.
  gone.forEach(dropTab);
}

let refreshBusy = false;     // a poll is out
let refreshAgain = false;    // ...and somebody asked for another while it was
// How many action answers applyNow has adopted: a poll sent before the last
// of them was read before that action, so its reply is older than the rows
// on screen (B294).
let adoptSeq = 0;

async function refresh(){
  // One at a time, and never dropped.
  //
  // /api/status runs git for every project, so it is seconds rather than
  // milliseconds on a cold share, and refreshSoon deliberately fires three
  // of these within four seconds while the fifteen-second poll carries on.
  // Without a guard they stack, and because each one costs the same git walk,
  // stacking makes every one of them slower: the load feeds itself. That is
  // the shape bug #44 was reported in: cards still on "loading…" minutes
  // after a restart, while the PHONE card, which fetches on its own, had
  // drawn fine.
  //
  // Asked while one is out, the request is remembered rather than dropped:
  // an explicit refresh after an action has to land, or the page shows the
  // state from before the thing the operator just did.
  if (refreshBusy){ refreshAgain = true; return; }
  refreshBusy = true;
  const adoptedBefore = adoptSeq;
  let fetched = false;     // the container answered; what failed is this page
  try{
    const r = preStatusUsed ? await fetch("/api/status")
                            : (preStatusUsed = true, await preStatus);
    // Signed out (the cookie expired, or the secret rotated): go to the
    // login page rather than showing a dead dashboard with a red dot.
    if (r.status === 401){ location.href = "/login?next=%2F"; return; }
    if (!r.ok) throw new Error("HTTP " + r.status);
    const got = await r.json();
    // An action's own answer was adopted while this poll was out: this
    // reply was read before that action, and drawing it put the row back
    // the way it was until the next poll, a locked padlock after an unlock
    // (B294). Dropped, and a fresh one asked for.
    if (adoptSeq !== adoptedBefore){ refreshAgain = true; return; }
    state = got;
    // A new run of the container under this page, noticed here or by the
    // revs poll, whichever answers first: its code is what that run serves,
    // so the page starts again rather than carrying on with the old code.
    // Ahead of everything below, the changelog above all: opened by this
    // page, it announced a build the page was not running, which is how the
    // operator met an old Global rules dialog under a new version's notes.
    // The reloaded page opens the changelog itself, and its tabs come from
    // the layout the server pruned of this container's dead sessions at boot.
    if (state.boot && bootSeen && state.boot !== bootSeen){ location.reload(); return; }
    welcomeOnce();
    fetched = true;
    // The bell reads what sessions have waiting for approval off this
    // payload (roadmap #27), so it is drawn from here as well as from the
    // phone and the page's own notes: a row that appeared with the poll
    // would otherwise wait for something else to happen to be seen.
    drawBell();
    // The account's scheme, on a browser that has never seen this account
    // (roadmap #25). localStorage is the PAINT path: the scheme is applied
    // at the top of this file before the stylesheet parses, and a value
    // fetched over the network would be a flash of the default followed by a
    // jump, so this only speaks when local has nothing to say. A pick made
    // HERE outranks the record, or picking a scheme on a phone would be
    // undone by the desktop's next poll.
    adoptTheme(state.theme, state.me);
    adoptMode(state.mode, state.me);
    // An account with no shell must not be sitting in one. The page opens on
    // a workspace terminal and the saved strip may carry more, both of which
    // predate knowing who is asking, so the first payload that says so is
    // where they go. Claude tabs stay: those are the console (roadmap #27).
    if (!mayShell()){
      const shells = tabs.filter(t => t.kind === "term" && !isClaude(t));
      if (shells.length) shells.forEach(t => dropTab(t.id));
    }
    if (state.boot) bootSeen = state.boot;
    // After the boot check above, which drops every Claude tab on a restart:
    // this would otherwise be reaping tabs that have already gone.
    reapDeadTerminals();
    if ($("dot").classList.contains("off")) $("dot").classList.remove("off");
    setAttr($("dot"), "aria-label", null);
    // The container's hostname, which answers "which BuilderBot am I looking
    // at", and on the ordinary box, where the container is called builderbot,
    // answers it with the word already three inches to its left. Two of the
    // same word reads as a rendering fault rather than as information, so it
    // is shown only when it says something the title does not.
    const host = state.host || "";
    setText($("host"), host.toLowerCase() === "builderbot" ? "" : host);
    // The word that tells two dashboards apart: on when dev features, the
    // ones not yet vetted, are offered here, which production never has.
    setHidden($("devtag"), !state.settings?.settings?.offer_unvetted?.value);
    drawSetup();
    setText($("uptime"), "up " + shortUptime(state.uptime));
    drawBuild(state.image);
    adoptLayout(state.layout);
    // Every part draws on its own from here (bug #44). They used to run as
    // one straight line, so a draw that threw on the payload took every
    // draw after it down with it, and the page kept the fact to itself. Now
    // the part that failed says so in its own body and the rest draw.
    // A page opened (or reloaded) while a clone is running starts watching
    // it here. Not through pJobSeen: that redraws the card itself and would
    // recurse into refresh() on a finish, so only the poll is started; the
    // job itself is already in state, where the card reads it.
    if (state.project_job?.running && !pJobTimer) pJobTimer = setTimeout(pJobPoll, 1000);
    drawCard("projects", () => drawProjects(state.projects));
    // An open notebook learns from the poll that a session has started or
    // finished a batch, without the operator having to touch anything.
    drawCard(null, () => notebooks.forEach(nb => {
      const p = (state.projects || []).find(x => x.name === nb.project);
      if (p) nb.poll(p);
    }));
    drawCard("sessions", () => drawSessions(state.sessions));
    drawCard(null, gateFindings);
    drawCard("linux", drawLinux);
    drawCard("commands", drawCommands);
    drawCard("git", drawGit);
    drawCard("custom", drawCustom);
    drawCard("doctor", drawDoctor);
    drawCard(null, watchSignin);
    // A scan re-ran on the host: drop the cache, and any notebook showing
    // its Analysis view re-reads on its poll below.
    const agesKey = (state.reports_ages || [])
      .map(r => r.name + (r.stale ? "!" : "")).join(",");
    if (findings && !findings.loading
        && ((findingsMtime !== null && state.reports_mtime !== findingsMtime)
            || (findings.agesKey !== undefined && findings.agesKey !== agesKey)))
      findings = null;
    if (findings && !findings.loading && findings.agesKey === undefined)
      findings.agesKey = agesKey;
    render();
    // Cleared at the END, not where the fetch landed: a poll that arrives
    // and then fails on this page is still a failed poll, and resetting the
    // count on arrival read every one of those as the first.
    pollFails = 0;
    const pw = $("pollWhy");
    if (pw && !pw.hidden){ pw.hidden = true; pw.textContent = ""; }
  }catch(e){
    // The light goes red either way; the console says whether the box was
    // unreachable or this page tripped over its own data.
    console.error("refresh:", e);
    $("dot").classList.add("off");
    // ...and the light says so in words, because red on its own does not.
    // A poll that keeps failing leaves every card that had not drawn yet
    // sitting at "loading…" forever, which reads as a hung page rather than
    // as an error: the operator described exactly that and had no way to
    // tell the two apart. The count is the useful half: one failure is a
    // blip, a rising number is the box or this page, and the reason names
    // which.
    //
    // Two different failures end up here, and they want different words: a
    // fetch that never landed is the box or the network, a payload that
    // arrived and then broke this page is a bug in this file. Calling the
    // second "not reaching the container" sends whoever reads it to check
    // the wrong machine.
    pollFails++;
    const n = `${pollFails} poll${pollFails === 1 ? "" : "s"} failed in a row`;
    const why = `Last reason: ${e && e.message ? e.message : e}`;
    // Said under the header from the second failure on (the light alone was
    // a tooltip, 11 Oct): one failed poll is a blip, two is a state.
    const said = fetched
      ? `the container answers, but this page fails on its answer: ${n}. ${why}`
      : `not talking to the container: ${n}. ${why}`;
    $("dot").setAttribute("aria-label", said);
    const pw = $("pollWhy");
    if (pw && pollFails > 1){ pw.textContent = said; pw.hidden = false; }
    if (pollFails > 1)
      // Every placeholder still waiting: the page's and the panels' own.
      document.querySelectorAll("main .loading").forEach(el => {
        el.textContent = fetched
          ? "not drawn: the page could not read the server's answer (the line under the header says why)"
          : "not loaded: the page is not reaching the container";
        el.classList.add("warn");
      });
  }finally{
    refreshBusy = false;
    if (refreshAgain){ refreshAgain = false; refresh(); }
    else statusLater();
  }
}

// The status poll's own clock (R218 step 10): the next read is due fifteen
// seconds after the last one, whoever asked for that one, so an action's
// read is not followed a moment later by the timer's; none is due while the
// page is hidden, where a git walk per project buys nothing nobody sees; and
// coming back to the page reads at once (its visibilitychange listener,
// beside the revisions poll's). It was a fixed interval: on time whether or
// not a read had just landed, and on, hidden or not.
const STATUS_MS = 15000;
let statusTimer = null;
function statusLater(){
  clearTimeout(statusTimer);
  statusTimer = document.hidden ? null : setTimeout(() => refresh(), STATUS_MS);
}

// Consecutive failed polls. Zero is healthy; the header's light carries the
// count and the reason once it is not.
let pollFails = 0;

// The Analysis button, and any tab already open on it. Ghosting the
// button is the ordinary half; closing an open tab is only done ONCE, when the
// page first learns there is nothing to read: a layout restored from the last
// session can carry an Analysis tab for a scanner that has since been
// unmounted, and leaving it open to say "nothing here" is a tab the operator
// has to close by hand. After that first answer a tab stays put: taking one
// out from under somebody mid-read, because a report went stale while they
// were looking at it, would be worse than the empty state it would leave.
let findingsGated = false;
function gateFindings(){
  const off = findingsOff();
  if (findingsGated) return;
  findingsGated = true;
  if (!off) return;
  tabs.filter(t => t.kind === "findings").forEach(t => hideTab(t.id));
}

// ---- what changed, and who cares ------------------------------------------

// A view says what it depends on; it never decides when to re-read. That
// decision was the source of four bugs in a week, every one of them a view
// reasoning about something it could not see: the roadmap's arrows and a
// session starting, the Artifacts tab and a phone connecting, and the Phone
// card polling only when it already knew of a request, which meant it could
// never find the first one.
//
// The tokens come from /api/revs, which is deliberately tiny: file mtimes and
// counters, no git, no tmux, no adb. That is what makes it affordable to ask
// every second, where /api/status is affordable every fifteen.
const revWatch = [];
let revs = {};

// `key` may be a name or a function returning one, because half of these are
// per project and the project is not known when the watch is registered.
//
// Returns the way to stop watching, and a per-project view MUST use it: a
// notebook's thirteen watches closed over a root that had been removed from
// the document, and kept firing: `showing()` reads .hidden off a detached
// element, which is still false, so every closed notebook went on fetching
// its artifacts and its version forever, once per token that moved.
function onRev(key, fn){
  const w = {key, fn};
  revWatch.push(w);
  return () => { const i = revWatch.indexOf(w); if (i >= 0) revWatch.splice(i, 1); };
}

// One out at a time, as refresh() is (R88): the timer, a tab coming back
// into view and a menu let go all start one, and with no guard an older
// reply landing second set revs back to the past, every watch fired again
// and every view's fetch doubled. Asked while one is out, it is remembered
// and asked once more when that one lands.
let revsBusy = false, revsAgain = false;
async function pollRevs(){
  // A notebook view draws from its own fetch, straight into its own element,
  // so the only place to hold one is here, before the watch that starts it.
  if (menuHolds(null)) return;
  if (revsBusy){ revsAgain = true; return; }
  revsBusy = true;
  try{ await pollRevsOnce(); }
  finally{
    revsBusy = false;
    if (revsAgain){ revsAgain = false; pollRevs(); }
  }
}
async function pollRevsOnce(){
  let now;
  try{
    // Which projects this page has a notebook open on. The per-project
    // tokens are watched by notebooks and by nothing else, so asking for the
    // whole share's would be a directory walk per project per second and a
    // half for panes nobody has open. Always sent, empty included: an absent
    // `p` means "all of them", which is what `bb` and the tests want.
    const ps = [...new Set(tabs.filter(t => t.kind === "notebook").map(t => t.arg))];
    const r = await fetch("/api/revs?p=" + encodeURIComponent(ps.join(",")));
    if (!r.ok) return;
    now = await r.json();
  }catch(e){ return; }
  // The container was replaced under this page. Everything it holds is from
  // a server that no longer exists, so the cheapest correct answer is to
  // start again rather than reconcile.
  if (revs.boot && now.boot && revs.boot !== now.boot){ location.reload(); return; }
  const was = revs;
  revs = now;
  // The first poll of a page has nothing to compare against, so nothing is
  // news; after that a token APPEARING is, and a token going away is not.
  //
  // Both halves of that are cases, not theory. A per-project token appears
  // when its notebook opens and stops being asked for when it closes, so
  // treating a disappearance as a change fires a dead notebook's watches,
  // and treating an appearance as no change loses anything that happened
  // between the notebook opening and the first poll that named it. Each
  // watch compares against the number its own panel last read, so a fire it
  // did not need costs nothing.
  const first = !Object.keys(was).length;
  // Anything moved: what the back-off below reads. A token only one page
  // draws counts only while that page is on show: a node's heartbeat moves
  // its numbers every poll, and counted everywhere it kept every page at a
  // second and a half for good (R218 step 10).
  if (first || Object.keys(now).some(k => was[k] !== now[k] && (!REVS_PAGE_ONLY[k] || REVS_PAGE_ONLY[k]())))
    revsMovedAt = Date.now();
  for (const w of revWatch){
    const k = typeof w.key === "function" ? w.key() : w.key;
    if (!k) continue;
    if (!first && now[k] !== undefined && was[k] !== now[k]){
      try { w.fn(k); } catch(e){}
    }
  }
}

// Fast while the tab is being looked at, slow while it is not, and the tab
// being hidden must not mean "stop", which was the mistake in the first cut
// of the phone view. A hidden tab is exactly where a request lands while
// nobody is watching, and a browser throttles background timers hard anyway;
// what matters is that whenever the page does get to run, it catches up.
// ...and slow while nothing moves (R218 step 2, the pages rule): a second
// and a half while something changed in the last minute, five seconds
// after, thirty while hidden. A chain of timeouts rather than an interval,
// so the next wait is decided after each poll.
let revTimer = null, revsMovedAt = Date.now();
const REVS_PAGE_ONLY = {"nodes.sample": () => shown("nodes")};
const REVS_IDLE_MS = 60000;
function revsDelay(){
  if (document.hidden) return 30000;
  return Date.now() - revsMovedAt > REVS_IDLE_MS ? 5000 : 1500;
}
function reschedRevs(){
  clearTimeout(revTimer);
  revTimer = setTimeout(() => { pollRevs().finally(reschedRevs); }, revsDelay());
}
