// Macros: commands typed into the shell being looked at, and only into a
// plain shell, never a Claude session, where a command would be sent as a
// prompt.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- macros -------------------------------------------------------------

// Where a macro should be typed: the tab being looked at, and only if it is a
// plain shell. Never a Claude one, where the command would not run at all but
// be submitted as a prompt; never some other tab the operator is not looking
// at; and null when there is nothing suitable, which grays the buttons out.
function macroTarget(){
  const here = tabOf(panes[active]);
  return here && here.kind === "term" && !isClaude(here) ? here : null;
}
// Every macro button (the runner card's, the bb card's, the custom ones)
// grays out unless the tab being looked at is a plain shell: a Claude tab
// would take the command as a prompt, a document has nowhere to type, no
// tab has nowhere at all, and quietly targeting (or opening) some other tab
// was a surprise. The button says where to go instead.
const macrosLive = () => !!macroTarget();
// What the active shell's directory offers the git/GitHub buttons. The
// verdict is the server's (each session row carries git/github, resolved
// from its cwd where WORKSPACE is known), so a `cd` shows up here on the
// next poll rather than the page re-deriving projects from path strings.
function shellCtx(){
  const t = macroTarget();
  const s = t && state?.sessions?.find(x => x.name === sessionOf(t.arg));
  return { git: !!(s && s.git), github: !!(s && s.github) };
}

function wireMacros(el){
  const live = macrosLive();
  const ctx = shellCtx();
  el.querySelectorAll("[data-m],[data-run]").forEach(b => {
    // data-need is what the button requires of the shell's directory beyond
    // being a shell at all: "git" wants a repository.
    const need = b.dataset.need || "";
    const ok = live && (!need || (need === "git" && ctx.git));
    setDisabled(b, !ok);
    // A dead one is ghosted and says nothing (the operator, 11 Oct: no
    // tooltips; a reason on the page is for a warning or an error).
    b.onclick = () => b.dataset.m ? macro(b.dataset.m) : macro(null, b.dataset.run);
  });
}

// Macros run in a terminal rather than reporting into a pane of their own: the
// output belongs where the operator can scroll it, page it, and follow a
// `bb toolchains install` that takes minutes: none of which a one-shot text box did.
async function macro(name, custom){
  const t = macroTarget();
  if (!t) return;                        // grayed out; a stray tap does nothing
  const session = sessionOf(t.arg);
  focusTab(t.id);
  if (!liveSessions().has(session)){
    // The iframe was only just created; tmux has not registered it yet.
    notify(`Opening ${tabLabel(t)}: press the button again once it is up.`);
    return;
  }
  try{
    const r = await postJSON("/api/send", custom ? {session, custom} : {session, macro:name});
    const j = await r.json();
    if (j.error) notify(j.error, true);
    else {
      notify(`${j.sent} → ${tabLabel(t)}`);
      // The phone's Commands flyout covers half the terminal, and the output
      // is what the tap was for: it slides away once the command is in.
      if (isPhone() && showMacros){ showMacros = false; drawKeys(); }
    }
  }catch(e){ notify("could not reach the dashboard: " + e, true); }
  refresh();
}
