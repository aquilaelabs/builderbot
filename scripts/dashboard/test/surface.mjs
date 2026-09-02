#!/usr/bin/env node
// The page's top-level surface, written down, so that changing it is a
// deliberate line in a diff rather than something that happens.
//
// index.html is one file of vanilla JS with no build step and no module
// boundary — the stated design, and the reason `bb dashboard test` can drive
// its internals directly. What it lacks is any way to notice code landing in
// the WRONG scope. That is not hypothetical: a feature written this week was
// declared three braces deep inside makeNotebook, a per-notebook factory, so
// the projects card calling it got "openTrash is not defined" — and an earlier
// one read a const before its initializer across ten thousand lines (bug #27).
// Both were eventually caught by a console error in a suite that happened to
// exercise the path. This catches them by name, in one place, immediately.
//
// It runs in BOTH directions on purpose.
//
//   MISSING means a name that used to be top-level is not any more — deleted,
//   renamed, or fallen into a nested scope. The last of those is the bug.
//
//   NEW means a global appeared. That is not an error, but it should be a
//   decision: this file already carries 84 mutable top-level bindings, and
//   every one of them is a thing two pieces of code can disagree about. Adding
//   a line here is the cost of adding one, and it is meant to be felt.
//
// A `function` or `var` at the top level of a classic script becomes a
// property of window; `let` and `const` go into the global LEXICAL scope,
// reachable by bare name and invisible to getOwnPropertyNames. So the
// inventory below covers the function/var half — 192 names — and the named
// check underneath asks by bare name instead, which is how the markup and the
// suite actually reach them. Worth knowing rather than discovering: a feature
// written entirely as `const fn = () => …` is not covered by the inventory.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';

// Sorted, and one entry per name. Regenerate by failing the test and reading
// what it prints — do not hand-edit it into agreement without looking at why
// it moved.
const SURFACE = [
  'adoptCards', 'adoptLayout', 'applyCards', 'applyNow', 'applyTheme',
  'argForSession', 'arriveBox', 'arriveRow', 'askPurge', 'cSeg', 'cSlide',
  'cSubmit', 'cardDropIndex', 'claudeMd', 'daemonHost', 'closeEditor', 'closeNewProject',
  'closePane', 'closeRename', 'closeSendToDocker', 'commandOrder',
  'currentTheme', 'deleteProject', 'dmAction', 'dnShow',
  'dnSubmit', 'docSurface', 'dockerJob', 'drawAuth', 'drawBell', 'drawBuild',
  'drawCommands', 'drawCustom', 'drawDoctor', 'drawKeys',
  'drawPanes', 'drawPhone', 'drawProjects', 'drawRunner', 'drawSessions',
  'drawShellCard', 'drawTabs', 'drawTrash', 'drawUiMenu', 'dressFrame',
  'dropElsewhere', 'dropIndex', 'dropTab', 'edgeScroll', 'editCustom',
  'endCardDrag', 'endDrag', 'endSession', 'evictFrames',
  'findingsRulesHtml', 'finishTabs', 'flip', 'focusTab', 'foldHeight',
  'fillNodeSelect', 'gateDocker', 'gateFindings', 'getNotebook', 'hiddenLabel', 'hideTab', 'imgAdder',
  'imgRow', 'killSession', 'layoutNow', 'leaveRow', 'level', 'loadDocker',
  'loadFindings', 'loadJobs', 'jobAct', 'jobTitle', 'jobStatePill', 'jobWhen', 'jobOutputs', 'loadNodes', 'nodeAct', 'nodeStatePill', 'nodeNumbers', 'nodeDraft', 'mountState', 'nodeConfFold', 'nodeRunnerSection', 'dmRouteLine', 'loadPackages', 'loadWire', 'logNote', 'logSection',
  'macro', 'macroTarget', 'makeNotebook', 'markUiMenu', 'mobPanel',
  'nbReadOnly', 'newShell', 'nextShell', 'nextStep', 'notify',
  'nudgeTerminals', 'onCardDrag', 'onDrag', 'onRev', 'openClaude',
  'openDevEnv', 'openDocker', 'openEditContainer', 'openLinkProject',
  'openNewContainer', 'openNewProject', 'openNotebook', 'openPackages',
  'openProjectsTab', 'openSendToDocker', 'openTab', 'openTrash', 'pDraw',
  'pJobAct', 'pJobPoll', 'pJobSeen', 'pJobWire', 'pNameShow', 'pOpen',
  'pShowKey', 'pSlide', 'paginate', 'paint', 'paintBar', 'paneStack',
  'phFetch', 'pinTo', 'pkgAct', 'pkgRow', 'pkgTickDots', 'placeCard',
  'placePinMenu', 'placeResumeMenu', 'placeTab', 'pollRevs', 'postCustom',
  'postTrash', 'projectRow', 'pushLayout', 'reapDeadTerminals',
  'reattachTerminals', 'openFindingsTab', 'openJobsTab', 'openNodesTab', 'openSettingsTab', 'renderFindingsInto', 'fxRows', 'fxFilter', 'fxBarHtml', 'fxBarBand', 'fxWireBar', 'reportAges', 'refresh', 'refreshSoon', 'renameProject', 'render',
  'renderDoc', 'renderDockerInto', 'renderGuarded', 'renderJobsInto', 'renderNodesInto', 'renderNotebookInto', 'renderSettingsInto',
  'renderPackagesInto', 'renderProjectsInto', 'reorderTabEls', 'repoOfUrl',
  'reschedRevs', 'resetCards', 'revealActiveTab', 'rnDrawAuth',
  'rnDrawPrefs', 'rnFillPrefs', 'rnLoadAuth', 'rnShow', 'rnSubmit',
  'roomForTab', 'saveCards', 'saveLayout', 'sendCode', 'sendKey',
  'sessionLabels', 'sessionOf', 'setBadge', 'setLocked', 'setPinned',
  'setProjectPinned', 'setView', 'shortUptime', 'shortUptime', 'shellCtx', 'show', 'showInStack',
  'signIn', 'signOut', 'slideBody', 'slideCard', 'slideDetails',
  'slideHidden', 'slidePanel', 'swapBox', 'startCardDrag', 'startClaude', 'startDrag',
  'tabLabel', 'tabLabels', 'tabTitle', 'tipOff', 'tipify', 'toggleBell',
  'toggleCard', 'togglePin', 'toggleUiMenu', 'unveil', 'updateArrows',
  'viewAfterRestart', 'watchSignin', 'wireLogSection', 'wireJobsTab', 'wireNodeConf', 'wireNodesTab', 'wireMacros',
  'wireProjectRows'
];

const browser = await launch();
const page = await newPage(browser);
await page.goto(URL);
await ready(page);

// Measured against a fresh iframe's window rather than a hardcoded list of
// browser builtins, so a Chromium upgrade adding an API does not read as the
// page growing a global.
const live = await page.evaluate(() => {
  const f = document.createElement('iframe');
  f.style.display = 'none';
  document.body.appendChild(f);
  const base = new Set(Object.getOwnPropertyNames(f.contentWindow));
  f.remove();
  return Object.getOwnPropertyNames(window)
    .filter(k => !base.has(k) && !/^\d+$/.test(k)).sort();
});

const declared = new Set(SURFACE);
const seen = new Set(live);
const missing = SURFACE.filter(n => !seen.has(n));
const added = live.filter(n => !declared.has(n));

ok(missing.length === 0,
   `every name the page declares at the top level is still there${
     missing.length ? ` — missing: ${missing.join(', ')}` : ''}`);
ok(added.length === 0,
   `and nothing has quietly become a global${
     added.length ? ` — new: ${added.join(', ')}` : ''}`);

// The ones other code reaches for by name: the inline handlers in the markup
// and the suite's own page.evaluate calls. Named separately because a generic
// "the list matches" failure does not say which of them the page just lost.
const REACHED = ['refresh', 'openTab', 'hideTab', 'tabOf', 'sessionOf',
                 'newShell', 'setProjectPinned', 'renameProject', 'drawProjects',
                 'drawSessions', 'drawBell', 'notify', 'openTrash', 'drawTrash',
                 'paint', 'slideCard', 'drawUiMenu', 'toggleBell'];
// By bare name, not through window: half of these are `const` arrows, which
// are in the global lexical scope and never become window properties. The
// question being asked is "can other code call this", and that is the form
// other code uses.
const kinds = await page.evaluate(names => names.map(n => {
  try{ return [n, new Function(`return typeof ${n}`)()]; }
  catch(e){ return [n, 'unreachable']; }
}), REACHED);
const notFn = kinds.filter(([, t]) => t !== 'function').map(([n]) => n);
ok(notFn.length === 0,
   `the names the markup and the suite call are callable at the top level${
     notFn.length ? ` — not: ${notFn.join(', ')}` : ''}`);

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
