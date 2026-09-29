// The Claude sign-in: which Anthropic account this account is signed in
// to, the flow that signs a node in, the code a person pastes back into
// it, and signing out.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- the Claude sign-in -------------------------------------------------

// Which Anthropic account this account is signed in to, under the doctor
// verdict: the first thing to get right on a new box, and the last place
// anybody would think to look for it on the command line. The login itself
// is a node's: each machine signs in for itself and keeps the grant it
// alone refreshes, so what is drawn here is the identity and nothing else.
function drawAuth(){
  const el = $("docAuth"), a = state?.claude_auth, lg = state?.signin;
  if (!a || a.unknown){ el.hidden = true; return; }
  el.hidden = false;
  // A sign-in is in progress: the two things it needs are a link that can be
  // tapped and somewhere to put the code. Neither is a terminal's strong
  // suit on a phone: a wrapped URL cannot be selected and a paste into a
  // canvas silently does not arrive, leaving the Enter after it to hand the
  // flow an empty code and earn a 400 that reads like the code was wrong.
  // Signed in wins over a flow that is still on screen. The sign-in terminal
  // outlives the sign-in: it ends by saying to press enter to close it, so
  // that a refusal can be read rather than vanishing, which left the card
  // asking for a code long after the code had worked.
  if (lg?.running && !a.signed_in){
    // Whatever is half-typed survives a repaint. The row is rebuilt whenever
    // anything in it changes (the link arriving, the flow moving on) and a
    // field that empties itself under a thumb mid-paste is how this looked
    // broken.
    const held = $("authCode")?.value || "";
    const hadFocus = document.activeElement === $("authCode");
    // Sign in stays, and stays meaning what it meant: start over. A code that
    // has expired, a page closed on the way back, a wrong account: the way
    // out of all of them is a fresh flow, and it must not be hidden behind
    // the field for the code of the flow that went wrong.
    if (paint(el, `
      ${lg.url ? `<a class="sub grow" href="${esc(lg.url)}" target="_blank"
           rel="noopener">open the sign-in page ↗</a>`
                : `<span class="sub grow">starting the sign-in…</span>`}
      <button id="bSignIn" title="start the sign-in again: the code from the
        one before it will not be accepted">Start over</button>
      <div class="codebox">
        <input id="authCode" autocomplete="off" spellcheck="false"
               autocapitalize="none" placeholder="paste the code here"${
          lg.waiting ? "" : " disabled"}>
        <button id="bAuthCode" class="primary" type="button"${
          lg.waiting ? "" : " disabled"}>${lg.sent ? "Signing in…" : "Send"}</button>
      </div>`)){
      $("authCode").value = held;
      // Restoring focus, not taking it: the row was rebuilt under someone who
      // was already typing in this field, and only they put it there.
      if (hadFocus && !$("authCode").disabled) $("authCode").focus();
      $("bSignIn").onclick = signIn;
      $("bAuthCode").onclick = sendCode;
      $("authCode").onkeydown = e => {
        if (e.key === "Enter"){ e.preventDefault(); sendCode(); }
      };
    }
    return;
  }
  // More than one node runs sessions, so the server asked which: signing in
  // on the wrong machine is a real mistake, and it will not pick for you. The
  // names come back with the refusal, so the choice is drawn from what it
  // said rather than from a second request.
  // One row: a select and the two buttons. A button per node stacked
  // vertically down a 340px card, which is what this was.
  if (signinPick){
    if (paint(el, `<span class="sub">sign in on</span>
        <select id="signinNode" class="grow" aria-label="which node">${
          signinPick.map(n => `<option>${esc(n)}</option>`).join("")}</select>
        <button id="bSignInOn" class="primary">Sign in</button>
        <button id="bSignInNo" class="bare">Cancel</button>`)){
      $("bSignInOn").onclick = () => { const n = $("signinNode").value; signinPick = null; signIn(n); };
      $("bSignInNo").onclick = () => { signinPick = null; drawAuth(); };
    }
    return;
  }
  // A sign-in that ended without signing anybody in. Said here, where it was
  // asked for, rather than in a terminal nobody can read on a phone.
  if (lg?.done && !lg.ok && !a.signed_in){
    if (paint(el, `<span class="sub grow bad">${esc(lg.error || "the sign-in did not finish")}</span>
       <button id="bSignIn" class="primary" title="start another">Try again</button>`))
      $("bSignIn").onclick = signIn;
    return;
  }
  const busy = claudeSessions();
  if (paint(el, a.signed_in
    ? `<span class="sub grow" title="${a.nodes === 1 ? "reported by the node that signed in"
         : `reported by the ${a.nodes} nodes that signed in`}, and the login stays there">signed in${
         a.email ? " as " + esc(a.email) : ""}${a.plan ? ` · ${esc(a.plan)}` : ""}</span>
       <button id="bSignOut"${busy.length ? " disabled" : ""} title="${busy.length
         ? `end ${busy.length === 1 ? "this session" : "these sessions"} first: ${
             esc(busy.join(", "))}`
         : "sign out of Claude, on every node holding this login"}">Sign out</button>`
    : `<span class="sub grow bad">not signed in to Claude: sessions will not start</span>
       <button id="bSignIn" class="primary"
         title="runs the sign-in on a node, with the code pasted back here">Sign in</button>`)){
    const out = $("bSignOut"), inb = $("bSignIn");
    if (out) out.onclick = signOut;
    if (inb) inb.onclick = signIn;
  }
}

// A staged bump that moves the compatibility window: minor and major do,
// patch does not, and only where this project owns the window at all.
const windowMove = (part, cost) =>
  (part === "minor" || part === "major") && (cost?.projects || []).length > 0;

// Which node a sign-in was asked about, when there was more than one to
// choose from. Drawn by drawAuth, cleared by choosing or canceling.
let signinPick = null;

// Sign in, however many times it takes. No terminal: the flow runs under a
// pty on the NODE (which is where Claude Code is installed) and the card
// does the rest, so this is one request from here.
//
// The ANSWER is read, and that is not a detail: this used to fire and forget,
// so a refusal (no node running sessions, or several and it will not pick)
// left the button reading "Starting…" for ever with nothing said anywhere.
// The card repaints only when its html changes, and a refusal changes
// nothing, so the button has to be put back here too.
async function signIn(node){
  const b = $("bSignIn");
  if (b){ b.disabled = true; b.textContent = "Starting…"; }
  let j = {};
  try{
    const r = await postJSON("/api/signin", node ? {node} : {});
    j = await r.json();
  }catch(e){ j = {error: "could not reach the server: " + e}; }
  if (j.nodes?.length > 1){
    signinPick = j.nodes;               // it asked which; the card asks you
    drawAuth();
    return;
  }
  if (j.error) notify(j.error, true);
  // The button on the page now, not the one pressed: a repaint while the
  // answer was on its way replaced it, and the copy it drew is whatever the
  // template says, so both are put back (B248).
  const b2 = $("bSignIn");
  if (b2 && b2.textContent === "Starting…"){ b2.disabled = false; b2.textContent = "Sign in"; }
  else if (b && document.body.contains(b)){ b.disabled = false; b.textContent = "Sign in"; }
  refresh();
}

// While a sign-in is going, the card is worth more than one look every fifteen
// seconds: the URL arrives a second in, and the answer to the code lands a
// second after it is sent. Stops the moment there is nothing running.
let signinTimer = null;
function watchSignin(){
  const lg = state?.signin;
  const live = lg?.running || (lg?.done && !lg.ok && !state?.claude_auth?.signed_in);
  if (live && !signinTimer) signinTimer = setInterval(() => refresh(), 1200);
  if (!live && signinTimer){ clearInterval(signinTimer); signinTimer = null; }
}

// The code from the browser, typed into the sign-in terminal for you. See the
// server's _login_code: the two steps a phone is worst at are the two this
// takes off it.
async function sendCode(){
  const f = $("authCode"), b = $("bAuthCode");
  const code = f.value.trim();
  if (!code) return f.focus();   // pressed Send with nothing in it
  b.disabled = true; b.textContent = "Sending…";
  try{
    const r = await postJSON("/api/login-code", {code});
    const j = await r.json();
    if (j.error) notify(j.error, true);
    else { f.value = ""; notify("sent: the card says what the sign-in makes of it"); }
  }catch(e){ notify("could not reach the server: " + e, true); }
  b.disabled = false; b.textContent = "Send";
  refresh();
}

async function signOut(){
  // Every node: one Anthropic account per BuilderBot account, so signing out
  // is signing out everywhere. A node that is not dialing in right now does
  // it when it comes back: the sentence says so rather than implying they
  // all go at once.
  if (!confirm("Sign out of Claude?\n\nThis signs out every node that holds "
               + "your login: one that is offline does it when it "
               + "reconnects. Sessions stop working until you sign in "
               + "again.")) return;
  const b = $("bSignOut");
  b.disabled = true; b.textContent = "Signing out…";
  try{
    const r = await fetch("/api/signout", {method:"POST",
      headers:{"Content-Type":"application/json"}, body: "{}"});
    const j = await r.json();
    if (j.error) notify(j.error, true);
    else notify(j.nodes?.length
      ? `signed out: ${j.nodes.join(", ")} ${j.nodes.length === 1 ? "follows" : "follow"} on their next sync`
      : "signed out");
  }catch(e){ notify("could not reach the server: " + e, true); }
  refresh();
}
