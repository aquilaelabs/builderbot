#!/usr/bin/env node
// The page's top-level surface, written down, so that changing it is a
// deliberate line in a diff rather than something that happens.
//
// index.html is one file of vanilla JS with no build step and no module
// boundary: the stated design, and the reason `bb dashboard test` can drive
// its internals directly. What it lacks is any way to notice code landing in
// the WRONG scope. That is not hypothetical: a feature written this week was
// declared three braces deep inside makeNotebook, a per-notebook factory, so
// the projects card calling it got "openTrash is not defined", and an earlier
// one read a const before its initializer across ten thousand lines (bug #27).
// Both were eventually caught by a console error in a suite that happened to
// exercise the path. This catches them by name, in one place, immediately.
//
// It runs in BOTH directions on purpose.
//
//   MISSING means a name that used to be top-level is not any more: deleted,
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
// inventory below covers the function/var half (192 names), and the named
// check underneath asks by bare name instead, which is how the markup and the
// suite actually reach them. Worth knowing rather than discovering: a feature
// written entirely as `const fn = () => …` is not covered by the inventory.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// Sorted, and one entry per name. Regenerate by failing the test and reading
// what it prints. Do not hand-edit it into agreement without looking at why
// it moved.
const SURFACE = [
  'adoptCards', 'adoptLayout', 'adoptTheme', 'applyCards', 'applyNow', 'applyTheme',
  'argForSession', 'armModal', 'arriveBox', 'arriveRow', 'askPurge', 'askReset', 'nginxHostPick', 'nginxHostLines', 'claudeRestart', 'unenrollWhat', 'resetBusy', 'resetFollow', 'resetGone', 'cSeg', 'cSlide',
  'askVerb', 'cSubmit', 'cUnderPicked', 'cardDropIndex', 'daemonHost', 'closeEditor',
  'closeNewProject', 'createProject',
  'closePane', 'closeRename', 'closeSendToDocker', 'commandOrder',
  'currentTheme', 'deleteProject', 'dmAction', 'dnShow',
  'dmState', 'dmWireRows', 'dnNodeSay', 'dnSubmit', 'docSurface', 'docSection', 'sectAttr', 'wireSections', 'openMenu', 'menuHolds', 'dmNodesKey', 'emuOnNodes', 'busy', 'unbusy', 'dockerJob', 'drawBell', 'attRow', 'drawBuild',
  'drawCommands', 'drawCustom', 'drawDoctor', 'drawKeys',
  'byProjectName', 'drawCard', 'drawPanes', 'drawProjects', 'drawRunner', 'drawSessions',
  'drawShellCard', 'drawTabs', 'drawTrash', 'drawUiMenu', 'dressFrame',
  'dropElsewhere', 'dropIndex', 'dropTab', 'edgeScroll', 'editCustom',
  'endCardDrag', 'endDrag', 'endSession',
  'findingsRulesHtml', 'finishTabs', 'drawTabPick', 'tabPickShow', 'flip', 'focusTab', 'foldHeight',
  'fillNodeSelect', 'fillUnderSelect', 'gateDocker', 'gateFindings', 'getNotebook', 'hiddenLabel', 'hideTab',
  'killSession', 'layoutNow', 'leaveRow', 'level', 'loadDocker',
  'loadFindings', 'loadJobs', 'jobAct', 'jobTitle', 'jobStatePill', 'jobWhen', 'jobOutputs', 'loadNodes', 'nodeContainerNetRow', 'nodePortsLocalRow', 'nodeHostRootRow', 'pressing', 'nodeAct', 'nodeStatePill', 'nodeTools', 'nodeGit', 'nodeGpu', 'fmtTime', 'userTZ', 'setUserTZ', 'tzOptions', 'profilePlugins', 'profileLogs', 'nodeDraft', 'mountState', 'nodeStale', 'nodeClaudeSection', 'windowGap', 'staleWhy', 'storeMoves', 'nodeDrift', 'nodeConfSections', 'nodeRunnerSection', 'nodeSessionsSection', 'nodeSessNetRow', 'nodeSyncRow', 'nodeHostRow', 'nodeDoorRow', 'openUnenroll', 'nodeProjects', 'nodeProjectsSection', 'nodeProjectRemove', 'nodeTurnsRow', 'nodeAdvancedSection', 'nodeMeters', 'meter', 'dmRouteLine', 'groupNodeOptions', 'openRelocate', 'rlSay', 'closeRelocate', 'rlSubmit', 'myProjectNames', 'dmRowsHtml', 'dmLogs', 'dmRefLine', 'dmGrantLine', 'dmOwnerLine', 'dmMoveLine', 'dmGroupsHtml', 'dmOtherRowsHtml', 'dmTestLine', 'dmBuilt', 'jobWhy', 'dockerTab', 'dockerNodeKeep', 'loadToolchains', 'loadWire', 'logNote', 'logSection',
  'chatLoop', 'chatOpen', 'consoleBar', 'drawChat', 'loadChat',
  'macro', 'macroTarget', 'makeNotebook', 'markUiMenu', 'mobPanel',
  'sessionRows', 'liveRefresh',
  'nbReadOnly', 'newShell', 'nextShell', 'nextStep', 'notify',
  'nudgeTerminals', 'onCardDrag', 'onDrag', 'onRev', 'openClaude',
  'openDevEnv', 'openDocker', 'openEditContainer', 'openEditInstance', 'cSaveInstance', 'openLinkProject',
  'openNewContainer', 'cFormYaml', 'cFormWrote', 'openNewProject', 'openNotebook', 'openToolchains', 'openPending', 'drawPendingModal', 'pendAct',
  'openProjectsTab', 'openSendToDocker', 'openTab', 'openTrash', 'pDraw',
  'nbAnalysisView', 'nbArtifactsView', 'nbBugsView', 'nbDesignView', 'nbGitView', 'nbHistoryView', 'nbMemoryView', 'nbPendingView', 'nbRoadmapView', 'nbRulesView', 'nbTestsView', 'nbWikiView', 'wikiMarkdown', 'wikiSlug', 'wikiToc', 'pullScroller', 'pullRefresh', 'wirePull', 'openReport', 'sendReport', 'pDrawForge', 'pUrlHost', 'postJSON', 'unlinkProject',
  'pFillGates', 'pFillNode', 'rnFillReads', 'tcClaudeRow', 'rnFillDebug', 'rnDebugNow', 'rnFillHosts', 'rnBars', 'rnBarSay', 'rnRevertSect', 'rnSectChanges', 'rnEnc', 'rnDec', 'pJobAct', 'pJobPoll', 'pJobSeen', 'pJobWire', 'pNameShow', 'pOpen',
  // A terminal in its own window (R8).
  'popOut', 'reattachTab',
  'pShowKey', 'pSlide', 'paginate', 'paint', 'paintBar', 'paneStack',
  'phFetch', 'pinTo', 'tcAct', 'tcPick',
  // The Emulator tab (tab-emulator.js).
  'openEmulator', 'emuPick', 'loadEmulator', 'emuAddRows', 'emuFlavorNow', 'emuTickedHere', 'emuRow', 'renderEmulatorInto', 'emuAct', 'tcRow', 'tcTermsLine', 'tcSystemLine', 'tcNeedsLine', 'tcDriverRow', 'tcDriverLine', 'tcDriverOption', 'tcToolkitRow', 'tcToolkitLine', 'nodesReadOnly',
  // The Claude sign-in on a node's row (page-signin.js), and the press that goes to it.
  'signinRev', 'signinCannot', 'signinBusy', 'signinBlock', 'wireSignin', 'openNodeClaude', 'signinCancel', 'claudeSigninFirst', 'claudeNodes', 'claudeEnd', 'modalTop', 'keepOpen', 'keepLine', 'pollRevsOnce', 'oneOpen', 'sectGroup', 'soleOpen', 'sectJump', 'topModal', 'modalOpened', 'modalClosed', 'modalFocusables', 'dismissModal', 'modalKeys', 'scrollHint', 'scrollHints',
  'openToolchainsOn', 'nodeGpuSection', 'nodeSound', 'tcTickDots', 'placeCard',
  'claudeNodeFacts', 'placePinMenu', 'placeResumeMenu', 'placeTab', 'pollRevs', 'postCustom',
  'postTrash', 'projectRow', 'phoneWhy', 'dmBootLine', 'nodePick', 'nodeToolsLine', 'openRunnerTab', 'renderPhoneInto', 'renderRunnerInto', 'phoneButton', 'phoneRowPress', 'openPhoneLend', 'openProjectSettings', 'settingsInto', 'settingsOut', 'pushLayout', 'readLocalPanes', 'keepLocalPanes', 'quietFields', 'reapDeadTerminals',
  'reattachTerminals', 'openFindingsTab', 'openJobsTab', 'openNodesTab', 'openSettingsTab', 'settingsKeep', 'gitLanes', 'renderDiff',
  'openPhoneTab', 'phonePanel', 'wirePhoneTab',
  'openStorageTab', 'loadStorage', 'storageFilesystems', 'storageStores', 'storageProjects', 'storageBody', 'storagePick', 'renderStorageInto', 'wireStorageTab',
  'openNginxTab', 'loadNginx', 'nginxAct', 'nginxRouteRow', 'nginxCertPick', 'nginxResolve', 'nginxCertLines', 'nginxRedraw', 'nginxDraftOf', 'nginxBody', 'nginxPick', 'renderNginxInto', 'nginxReadDraft', 'wireNginxTab',
  // The welcome panel (the About popup grown a guide and the changelog). The
  // guides are top-level consts, which are not window properties.
  'abShow', 'abLoadLog', 'abDrawLog', 'openAbout', 'closeAbout', 'welcomeOnce',
  'proseline', 'proselines',
  // The Users tab (roadmap #22 step 3). Functions only: a top-level `let`
  // is not a window property, so usersList and friends are not listed here.
  'openUsersTab', 'loadUsers', 'usersAct', 'userRow', 'usersEditOpen', 'usersEditSave',
  'renderUsersInto', 'wireUsers', 'openRolesTab', 'loadRoles', 'rolesAct', 'rolesFrom', 'rolesPeopleBody', 'rolesCanDo', 'rolesPeopleDirty', 'rolesPeopleFrom', 'rolesPerson', 'rolesRedraw', 'rolesRoleBody', 'rolesRoleDirty', 'renderRolesInto', 'wireRoles', 'openProfileTab', 'loadProfile', 'renderProfileInto', 'wireProfile', 'renderFindingsInto', 'fxRows', 'fxFilter', 'fxBarHtml', 'fxBarBand', 'fxWireBar', 'reportAges', 'refresh', 'refreshSoon', 'renameProject', 'render',
  'idleSection', 'wireIdleSection', 'pathsSection', 'wirePathsSection', 'settingsSections', 'withRevert', 'tunnelSteps', 'tunnelStatus', 'wireSettingsSections', 'settingsLive', 'openDebugSettings',
    'reportsSection', 'clearReports',
  'renderDoc', 'renderDockerInto', 'renderGuarded', 'renderJobsInto', 'renderNodesInto', 'renderNotebookInto', 'renderSettingsInto',
  'renderToolchainsInto', 'renderProjectsInto', 'reorderTabEls', 'repoOfUrl',
  'reschedRevs', 'resetCards', 'revealActiveTab', 'rnDrawAuth', 'rnDrawKey', 'rnKeyAct', 'drawSetup', 'setupFinish', 'setupNeeded', 'setupNode',
  'rnDrawPeople', 'rnDrawPrefs', 'rnFolds', 'rnTestAuth', 'rnLoadFtp', 'rnDrawReach', 'rnReachNodes', 'rnReachNow', 'rnReachSync', 'rnFtpWhere', 'rnDrawFtp', 'rnFtpChange', 'rnSaveFtp', 'rnDrawSigning', 'rnFillColor', 'rnFillNode', 'rnFillNodesMore', 'rnFillPrefs', 'rnFillPrefsRest', 'rnLoadAuth', 'rnLoadPeople', 'rnLoadSigning', 'rnLoadSnapshots', 'rnDrawSnapshots', 'rnSavePeople', 'rnSaveSigning', 'rnSessionEnd', 'rnSessionsDraw', 'rnSessionsLoad', 'rnFolderLine', 'ghName', 'rnShow', 'rnSubmit',
  'roomForTab', 'saveCards', 'saveLayout', 'sendCode', 'sendKey',
  'sessionLabels', 'sessionOf', 'setBadge', 'setLocked', 'setPinned',
  'setProjectPinned', 'setView', 'shortUptime', 'shortUptime', 'shellCtx', 'show', 'showInStack',
  'signIn', 'signOut', 'slideBody', 'slideCard', 'fadeFoldCard', 'slideDetails',
  'slideHidden', 'slidePanel', 'swapBox', 'startCardDrag', 'startClaude', 'sendSure', 'launchClaude', 'startDrag',
  'openBrief', 'closeBrief', 'briefGo', 'pArchivePicked',
  'tabLabel', 'tabLabels', 'tabTitle', 'untitle', 'untitleIn', 'untitleWatch', 'helpToggle', 'cLock', 'dmUnrouted', 'nodeDoorConfig', 'nginxUndeployed', 'resumePicker', 'toggleBell',
  'toggleCard', 'togglePin', 'toggleUiMenu', 'unveil', 'updateArrows',
  'viewAfterRestart', 'watchSignin', 'wireConsole', 'wireLogSection', 'wireJobsTab', 'wireNodeConf', 'wireNodesTab', 'wireMacros',
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
    .filter(k => !base.has(k) && !/^\d+$/.test(k) && !k.startsWith('__bbcov')).sort();  // the coverage counters, under bb tests coverage
});

const declared = new Set(SURFACE);
const seen = new Set(live);
const missing = SURFACE.filter(n => !seen.has(n));
const added = live.filter(n => !declared.has(n));

ok(missing.length === 0,
   `every name the page declares at the top level is still there${
     missing.length ? `; missing: ${missing.join(', ')}` : ''}`);
ok(added.length === 0,
   `and nothing has quietly become a global${
     added.length ? `; new: ${added.join(', ')}` : ''}`);

// The ones other code reaches for by name: the inline handlers in the markup
// and the suite's own page.evaluate calls. Named separately because a generic
// "the list matches" failure does not say which of them the page just lost.
const REACHED = ['refresh', 'openTab', 'hideTab', 'tabOf', 'sessionOf',
                 'newShell', 'setProjectPinned', 'renameProject', 'drawProjects',
                 'drawSessions', 'drawBell', 'notify', 'openTrash', 'drawTrash',
                 'paint', 'slideCard', 'drawUiMenu', 'toggleBell'];
// NOT the bridges out of makeNotebook: ruleStagedCount and its version
// equivalents. They are top-level `let`, and `new Function` below cannot see
// the global LEXICAL environment, so asking about one here answers
// "unreachable" for a name that is reachable from every line of the file.
// What guards those is behavioral: the panel's Save writes a rule and a
// version bump, and rules.mjs and version.mjs press it.
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
     notFn.length ? `; not: ${notFn.join(', ')}` : ''}`);

// Every name a script reads or writes is declared at the top level of some
// script the page loads, or is the browser's. Code moved into a view file
// keeps calling what it called before, and a name that stayed behind in the
// closure it came from is a ReferenceError the first time that path runs;
// a bare WRITE to one is worse, a stray global and no error at all. Four
// did exactly that on 16 Sep, on paths no suite happened to press. This is a
// read of the source rather than a run of it: Babel's scope tracker, which
// Playwright carries, resolves every reference to its binding.
const DASH = join(dirname(fileURLToPath(import.meta.url)), '..');
const { babelParse, traverse } = createRequire(import.meta.url)('playwright/lib/transform/babelBundle');
const html = readFileSync(join(DASH, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script(?: src="([^"]+)")?>([\s\S]*?)<\/script>/g)].map(m => m[1]
  ? {file: m[1], code: readFileSync(join(DASH, m[1]), 'utf8'), base: 0}
  : {file: 'index.html', code: m[2], base: html.slice(0, m.index).split('\n').length - 1});
const browserNames = await page.evaluate(() => {
  const f = document.createElement('iframe');
  f.style.display = 'none';
  document.body.appendChild(f);
  const names = new Set();
  for (let o = f.contentWindow; o; o = Object.getPrototypeOf(o))
    Object.getOwnPropertyNames(o).forEach(k => names.add(k));
  f.remove();
  return [...names];
});
const known = new Set(browserNames), uses = [];
for (const s of scripts)
  traverse(babelParse(s.code, s.file.replace(/\.html$/, '.js'), false), {Program(p){
    Object.keys(p.scope.bindings).forEach(n => known.add(n));
    for (const [n, node] of Object.entries(p.scope.globals))
      uses.push({n, at: `${s.file}:${s.base + (node.loc?.start.line || 0)}`});
    p.stop();
  }});
const stray = uses.filter(u => !known.has(u.n)).map(u => `${u.n} (${u.at})`);
ok(scripts.length > 2 && known.size > 500 && stray.length === 0,
   `every name the page's ${scripts.length} scripts use is declared by one of them or is the browser's${
     stray.length ? `; declared nowhere: ${stray.join(', ')}` : ''}`);

// The other half of that seam. A view reaches the notebook's helpers and the
// other views through the state object (nb.syncSave(), nb.shutSendBoxes), so
// a name one view stops handing back, or a helper the closure stops putting
// there, is a TypeError on some later click rather than a ReferenceError
// anybody can see by name. Every nb.NAME read must be put on nb by an
// assignment, by Object.assign's literal, or by the return of a view factory
// that is assigned to it.
const isState = p => {
  const fn = p.scope.getBinding('nb')?.scope.path.node;
  return fn?.type === 'FunctionDeclaration' && /^(makeNotebook|nb\w+View)$/.test(fn.id?.name || '');
};
const put = new Set(), reads = [], hands = {}, assignedFrom = [];
for (const s of scripts)
  traverse(babelParse(s.code, s.file.replace(/\.html$/, '.js'), false), {
    FunctionDeclaration(p){
      if (!/^nb\w+View$/.test(p.node.id.name)) return;
      const ret = p.node.body.body.findLast(st => st.type === 'ReturnStatement');
      hands[p.node.id.name] = (ret?.argument?.properties || []).map(q => q.key.name);
    },
    CallExpression(p){
      const c = p.node.callee, [target, from] = p.node.arguments;
      if (c.type !== 'MemberExpression' || c.object.name !== 'Object' || c.property.name !== 'assign'
          || target?.type !== 'Identifier' || target.name !== 'nb' || !isState(p)) return;
      if (from?.type === 'ObjectExpression') from.properties.forEach(q => put.add(q.key.name));
      if (from?.type === 'CallExpression' && from.callee.type === 'Identifier') assignedFrom.push(from.callee.name);
    },
    MemberExpression(p){
      const n = p.node;
      if (n.computed || n.object.type !== 'Identifier' || n.object.name !== 'nb' || !isState(p)) return;
      if (p.parentPath.isAssignmentExpression() && p.parent.left === n) put.add(n.property.name);
      else reads.push({n: n.property.name, at: `${s.file}:${s.base + n.loc.start.line}`});
    },
  });
assignedFrom.forEach(f => (hands[f] || []).forEach(n => put.add(n)));
const unput = [...new Set(reads.filter(r => !put.has(r.n)).map(r => `nb.${r.n} (${r.at})`))];
ok(reads.length > 100 && assignedFrom.length > 5 && unput.length === 0,
   `every one of the ${reads.length} reads of the notebook's state finds a name something puts there${
     unput.length ? `; put nowhere: ${unput.join(', ')}` : ''}`);

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
