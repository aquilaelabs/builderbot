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
const SURFACE = [ 'adoptLayout', 'adoptMode', 'adoptMotion', 'applyMotion', 'adoptTheme', 'applyMode', 'applyNow', 'askProjectGroup', 'renameProjectGroup', 'pickProjectColor', 'applyTheme',
  'sectRemember', 'sectRecall', 'isToolKind', 'groupOf', 'railAllows', 'railGroups', 'railOn', 'railGo', 'shellPush', 'routeOf', 'openRoute', 'shellSync', 'shellBoot', 'shown',
  'drawRail', 'railMoreShow', 'shellBar', 'wireShellBar', 'jumpItems', 'drawJump', 'jumpMove', 'jumpGo', 'wireJump', 'revsDelay',
  'argForSession', 'agentsLive', 'agExtras', 'agentPicker', 'agentAsker', 'rnFillAgents', 'launchAgent', 'agentEnd', 'dropAgentTab', 'myLiveSession', 'agentLogins', 'sendAgent', 'openSentTo', 'openAgentsTab', 'openAgentsOn', 'agPick', 'loadAgents', 'agentsLiveKey', 'agSection', 'renderAgentsInto', 'wireAgentsTab', 'agentById', 'agentOfSession', 'agentSessionWords', 'agentOfArg', 'agentsWord', 'agentArg', 'agentSessionName', 'mySlots', 'freeSlot', 'loadRmConvs', 'pickSend', 'armModal', 'arriveBox', 'askPurge', 'askReset', 'nginxHostPick', 'nginxHostLines', 'claudeRestart', 'restartNow', 'unenrollWhat', 'resetBusy', 'resetFollow', 'resetGone', 'cSeg', 'cSlide',
  'askVerb', 'cSubmit', 'cUnderPicked', 'daemonHost', 'closeEditor',
  'closeNewProject', 'createProject',
  'closeRename', 'closeSendToDocker', 'commandButton', 'wireTacks', 'bootPage', 'bootRail', 'skSplit', 'dockDragStart', 'dockDragMove', 'dockDragEnd', 'dockHeld', 'dockNoScroll', 'dockPlaceTab', 'nodeCharted',
  'currentMode', 'currentTheme', 'deleteProject', 'dmAction', 'dnShow',
  'dmState', 'dmWireRows', 'dmViewSeg', 'dmViewWire', 'dmCheck', 'dnNodeSay', 'dnSubmit', 'docSurface', 'docSection', 'skel', 'skv', 'skRows', 'skTpl', 'skTable', 'skProjectCard', 'projectsShown', 'slideCards', 'pjFadeArm', 'faceFade', 'showNewCard', 'skNodeBar', 'barSaid', 'dmBar', 'dmTiles', 'dmBootLoad', 'dmStatus', 'dmImagesSection', 'ndBar', 'ndFacts', 'ndDialogs', 'nodeSessSettings', 'nodeSessDirty', 'setupSteps', 'wireSetup', 'homeStartHtml', 'homeStartReadsNodes', 'storageBar', 'phoneBar', 'nginxBar', 'jobsSection', 'tcSections', 'tpSeen', 'tpModalHtml', 'tpSection', 'tpWire', 'tpOpen', 'tpFromHtml', 'tpSource', 'helpTitles', 'jobSessionWords', 'jobsToday', 'phWhy', 'tpClose', 'tpDraw', 'tpLook', 'emuSections', 'emuAddBar', 'sectFixed', 'sectNewVisit', 'ndAgentButtons', 'ndTitle', 'homeCards', 'openHelp', 'loadHelp', 'helpRead', 'helpNames', 'helpGo', 'helpScroll', 'helpNav', 'helpArticle', 'helpResults', 'helpSearch', 'renderHelpInto', 'rolesSplit', 'askSignOut', 'pageLink', 'askInline', 'navPush', 'dmImage', 'railTool', 'sectAttr', 'wireSections', 'openMenu', 'openPopup', 'menuHolds', 'actMore', 'statTiles', 'viewGlance', 'factGrid', 'pageHead', 'saveBar', 'dlgFoot', 'rmIcon', 'noNodeYet', 'chipBar', 'chipButtons', 'rmMatch', 'versionChips', 'bugMatch', 'bugFacts', 'rmDay', 'shippedIn', 'clRefs', 'clLinks', 'dmChipGroups', 'loadDockerStats', 'dmStatStrip', 'loadRowLog', 'dmFollowTick', 'loadDockerImages', 'dmHealth', 'dmRowWrap', 'dmPorts', 'dmOpenWhy', 'dmOpenSoon', 'dmRoutesOf', 'dmMatch', 'wireMore', 'closeMore', 'floatAt', 'floatPlace', 'floatFollow', 'cardPress', 'dmNodesKey', 'emuOnNodes', 'busy', 'unbusy', 'dockerJob', 'drawBell', 'drawMaintBand', 'attRow', 'drawBuild', 'dmJumpLoad', 'dmJumpRows', 'dmJumpTo',
  'drawCommands', 'drawCustom', 'drawDoctor', 'drawKeys',
  'byProjectName', 'byProjectGroup', 'bootView', 'optionList', 'nodeBar', 'ruleWhen', 'segPick', 'skField', 'abortBtn', 'dropBox', 'drawCard', 'drawPanes', 'drawProjects', 'renderSessionsInto', 'openSessionsTab', 'sessionProject',
  'drawShellCard', 'drawTrash', 'drawUiMenu', 'dressFrame',
  'dropElsewhere', 'dropTab', 'editCustom', 'endSession',
  'findingsRulesHtml', 'flip', 'focusTab', 'foldHeight',
  'fillNodeSelect', 'fillUnderSelect', 'gateDocker', 'gateFindings', 'dropGoneNotebooks', 'getNotebook', 'hideTab',
  'killSession', 'layoutNow', 'level', 'loadDocker',
  'loadFindings', 'loadJobs', 'jobAct', 'jobTitle', 'jobsShown', 'jobsShowSet', 'jobStatePill', 'jobWhen', 'jobSince', 'jobOutputs', 'loadNodes', 'loadNodesOnce', 'nodeContainerNetRow', 'nodePortsLocalRow', 'nodeHostRootRow', 'pressing', 'nodeAct', 'nodeStatePill', 'nodeTools', 'nodeGit', 'nodeGpu', 'fmtTime', 'userTZ', 'setUserTZ', 'tzOptions', 'profileDevices', 'nodeDraft', 'mountState', 'nodeStale', 'windowGap', 'staleWhy', 'storeMoves', 'ndStoreAsk', 'nodeDrift', 'nodeConfSections', 'nodeRunnerSection', 'nodeSessionsSection', 'nodeSessNetRow', 'nodeSyncRow', 'nodeSyncSaid', 'nodeHostRow', 'nodeDoorRow', 'openUnenroll', 'nodeProjects', 'nodeProjectsSection', 'nodeTurnsRow', 'nodeAdvancedSection', 'nodeMeters', 'meter', 'dmRouteLine', 'groupNodeOptions', 'openRelocate', 'rlSay', 'closeRelocate', 'rlSubmit', 'myProjectNames', 'dmRowsHtml', 'dmLogs', 'dmRefLine', 'dmOverrideLine', 'dmClaudeSaid', 'dmOwnerLine', 'dmMoveLine', 'dmNginxLine', 'dmSetGrid', 'dmSetDialog', 'dmRowDirty', 'runnerAddBtn', 'storageMeasureBtn', 'storageFreeable', 'storagePhones', 'dockerPrune', 'emuPhonesSaid', 'emuPhones', 'dmServicesTable', 'dmUpFor', 'dmUptime', 'dmOpenLink', 'dmPortsSaid', 'dmSetPills', 'dmInstPills', 'dmDropDrafts', 'factPills', 'dmGroupsHtml', 'dmOtherRowsHtml', 'dmTestSaid', 'dmBuilt', 'jobWhy', 'dockerTab', 'dockerNodeKeep', 'loadToolchains', 'loadWire', 'logNote', 'logSection', 'nodeAgentsHere', 'nodeAgentsLine',
  'chatOpen', 'consoleBar', 'drawChat', 'loadChat', 'openChatTab', 'renderChatInto', 'drawChatList', 'drawChatThread',
  'macro', 'macroTarget', 'makeNotebook', 'markUiMenu', 'mobPanel',
  'sessionRows', 'liveRefresh', 'bootFetch', 'bootReadsDone',
  'nbReadOnly', 'newShell', 'nextShell', 'nextStep', 'notify',
  'nudgeTerminals', 'termOwn', 'xtermReady', 'termSlot', 'termUrl', 'termMount', 'termSend', 'termType', 'termFit', 'termConnect', 'termEnded', 'termDrop', 'termSweep', 'termRevive', 'termKey', 'termLog', 'openLogTab', 'termProject', 'termPalette', 'termPreview', 'termLookPicked', 'rnTermPreview', 'termLook', 'termRestyle', 'termTouch', 'termCell', 'termScroll', 'termPos', 'termSelectAt', 'termSelectDraw', 'termSelText', 'termCopy', 'termSelectEnd', 'profileTerminal', 'wireTerminalLook', 'onRev', 'openClaude',
  'openDevEnv', 'openDocker', 'openDockerOn', 'openEditContainer', 'openEditInstance', 'cSaveInstance', 'openLinkProject',
  'openNewContainer', 'cFormYaml', 'cFormWrote', 'openNewProject', 'openAddRepository', 'openNotebook', 'openToolchains', 'openPending', 'drawPendingModal', 'pendAct',
  'openProjectsTab', 'openSendToDocker', 'openTab', 'openTrash', 'pDraw',
  'nbAnalysisView', 'nbArtifactsView', 'nbBugsView', 'nbDesignView', 'nbGitView', 'nbHistoryView', 'nbMemoryView', 'nbPendingView', 'chipsScrolled', 'chipsEdge', 'chipsEdges', 'chipsArrow', 'chipsDown', 'chipsMove', 'chipsUp', 'chipsClickGuard', 'chipsRestore', 'dmHostOnly', 'nbPermsView', 'nbSessionsView', 'convRows', 'resumeConversation', 'nbRoadmapView', 'nbRulesView', 'nbSigningView', 'nbTestsView', 'nbWikiView', 'wikiMarkdown', 'wikiSlug', 'wikiToc', 'wikiNav', 'wikiUntitled', 'wikiContents', 'wikiScroll', 'wikiArticle', 'pullScroller', 'pullRefresh', 'wirePull', 'openReport', 'reportConvFor', 'sendReport', 'pDrawForge', 'pUrlHost', 'postJSON', 'unlinkProject',
  'pFillGates', 'pFillNode', 'pDirOf', 'dmCalled', 'dmJobSettle', 'rnFillReads', 'rnLoadTools', 'rnFillTools', 'rnLockSettings', 'rnRowsList', 'rnFillDebug', 'rnDebugNow', 'rnHostIds', 'rnBars', 'rnBarSay', 'rnRevertSect', 'rnSectChanges', 'rnEnc', 'rnDec', 'pJobAct', 'pJobPoll', 'pJobSeen', 'pJobWire', 'pNameShow', 'pOpen',
  // A terminal in its own window (R8).
  'popOut', 'reattachTab',
  'pShowKey', 'pSlide', 'paginate', 'paint', 'paintBar', 'paneStack',
  'phFetch', 'tcAct', 'tcPick',
  // The Emulator tab (tab-emulator.js).
  'openEmulator', 'emuPick', 'loadEmulator', 'emuAddRows', 'emuFlavorNow', 'emuTickedHere', 'emuRow', 'renderEmulatorInto', 'emuAct', 'tcRow', 'tcTermsLine', 'tcVerifiedLine', 'tcSystemLine', 'tcNeedsLine', 'tcDriverRow', 'tcDriverLine', 'tcDriverOption', 'tcToolkitRow', 'tcToolkitLine', 'nodesReadOnly', 'headerOnly', 'splitSects', 'splitDraw', 'splitAway', 'bootOwn', 'splitMove', 'splitMarks', 'splitOff', 'rnSplit', 'rolesInsts', 'rolesLvlAt', 'rolesSetAll', 'viewSaid', 'pageKey', 'pageLimit', 'rnPrefsOf',
  // The Claude sign-in on a node's row (page-signin.js), and the press that goes to it.
  'signinRev', 'signinCannot', 'signinBusy', 'signinBlock', 'wireSignin', 'openNodeClaude', 'signinCancel', 'claudeSigninFirst', 'claudeNodes', 'claudeEnd', 'modalTop', 'keepOpen', 'keepLine', 'pollRevsOnce', 'oneOpen', 'sectGroup', 'soleOpen', 'sectJump', 'topModal', 'modalOpened', 'modalClosed', 'modalFocusables', 'dismissModal', 'modalKeys', 'scrollHint', 'scrollHints',
  'openToolchainsOn', 'nodeGpuSection', 'nodeSound', 'nodeInternet', 'ndOffLine', 'tcTickDots',
  'claudeNodeFacts', 'placeResumeMenu', 'pollRevs', 'postCustom',
  'postTrash', 'phoneWhy', 'dmBootLine', 'nodePick', 'openRunnerTab', 'renderPhoneInto', 'renderRunnerInto', 'phoneRowPress', 'openPhoneLend', 'openProjectSettings', 'settingsInto', 'settingsOut', 'pushLayout', 'readLocalPanes', 'keepLocalPanes', 'quietFields', 'reapDeadTerminals',
  'reattachTerminals', 'openFindingsTab', 'openJobsTab', 'openSchedulesTab', 'loadSchedules', 'postSchedule', 'schedWhen', 'schedRow', 'schedForm', 'schedAs', 'openSchedForm', 'closeSchedForm', 'wireSchedForm', 'renderSchedulesInto', 'wireSchedules', 'openNodesTab', 'openSettingsTab', 'settingsKeep', 'settingsWake', 'loadReports', 'deleteReport', 'gitLanes', 'renderDiff',
  'openPhoneTab', 'phonePanel', 'wirePhoneTab',
  'openStorageTab', 'loadStorage', 'storageHeld', 'storageRow', 'andList', 'storageDisks', 'storageProjects', 'storageBody', 'storagePick', 'renderStorageInto', 'wireStorageTab',
  'tourSeen', 'tourSoon', 'tourLoading', 'tourSample', 'tourSampleProject', 'tourFlip', 'tourSampleCard', 'tourTarget', 'tourStart', 'tourKeepSample', 'tourDraw', 'glanceWaiting', 'tourGo', 'tourEnd', 'tourLeft', 'tourReset', 'rnVmCapsOf', 'rnVmCapsNow', 'rnVmCapsSet', 'openVmsTab', 'loadVms', 'vmPill', 'vmRow', 'nodeFeaturesSection', 'vmGroupsHtml', 'vmBar', 'renderVmsInto', 'wireVms', 'openNewVm', 'vmHwLine', 'vmHwFields', 'vmHwRead', 'vmHwWire', 'openVmHardware', 'vmConsolesChecked', 'vmReapConsoles',
  'openNginxTab', 'loadNginx', 'nginxKeepTyping', 'nginxRefocus', 'projectHeader', 'wireProjectHeader', 'wireProjectMenu', 'reposAlso', 'projectState', 'claudeDeadWhy', 'agentInstall', 'projectNote', 'projectActions', 'projectMatches', 'lockMark', 'projFacts', 'projectCard', 'reposOf', 'projectList', 'cardMarks', 'cardLock', 'cardFront', 'cardNotes', 'cardBack', 'flipCard', 'newProjectByName', 'renameProjectCard', 'renameRepository', 'moveRepository', 'deleteProjectCard', 'wireProjectCards', 'agentButton', 'fxRemember', 'projectJobHtml', 'dockKeep', 'dockPlace', 'dockSettle', 'dockShow', 'dockToggle', 'dockBar', 'wireDockBar', 'dockReveal', 'dockEdges', 'dockDress', 'toggleDoctor', 'runnerRows', 'dmShellWhy', 'dmShell', 'openHome', 'homeOpen', 'loadHome', 'homeUpdates', 'homeTiles', 'homeTilesHtml', 'homeHref', 'homeJobsHtml', 'homeGlanceHtml', 'homeAttention', 'renderHomeInto', 'needsRows', 'wireNeeds', 'openJob', 'toastAdd', 'toastTick', 'toastHold', 'toastGone', 'tblTracks', 'tblWrap', 'tblLine', 'jobNode', 'jobTook', 'jobBy', 'sparkSvg', 'hourChart', 'wireCharts', 'nodeCharts', 'setText', 'setAttr', 'setClass', 'setHidden', 'setDisabled', 'setTitle', 'statusLater', 'dmLineWrap', 'dmLineCells', 'dmOtherWrap', 'keepNotice', 'askTag', 'askCmd', 'askLeft', 'askWho', 'askActs', 'askAnswer', 'notifyJob', 'jobToastsCheck', 'openNotices', 'loadNotices', 'noticesAct', 'noticesAskRows', 'noticesWaitingRows', 'noticesShown', 'renderNoticesInto', 'wireNotices', 'resumeHostNow', 'syncResumeMenu', 'nginxAct', 'nginxTls', 'nginxRouteForm', 'nginxRoutesTable', 'nginxCertPick', 'nginxResolve', 'nginxCertLines', 'nginxRedraw', 'nginxDraftOf', 'nginxBody', 'ngSect', 'nginxPick', 'renderNginxInto', 'nginxReadDraft', 'wireNginxTab',
  // The welcome panel (the About popup grown a guide and the changelog). The
  // guides are top-level consts, which are not window properties.
  'abShow', 'abGuideText', 'abLoadGuide', 'abLoadLog', 'abDrawCredits', 'abDrawLog', 'openAbout', 'closeAbout', 'welcomeOnce',
  'proseline', 'proselines',
  // The Users tab (roadmap #22 step 3). Functions only: a top-level `let`
  // is not a window property, so usersList and friends are not listed here.
  'openUsersTab', 'loadUsers', 'usersAct', 'userRow', 
  'renderUsersInto', 'wireUsers', 'usersEditFrom', 'usersPicked', 'usersDirty', 'usersRedraw', 'usersReadOnly', 'usersDetail', 'wireUsersBar', 'usersSave', 'usersAddOpen', 'rolesAccessFields', 'wireRolesAccess', 'rolesAccessSave', 'rolesAccessOpen', 'rolesNewOpen', 'openRolesTab', 'loadRoles', 'rolesAct', 'rolesFrom', 'rolesCanDo', 'rolesPeopleDirty', 'rolesPeopleFrom', 'rolesPerson', 'rolesRedraw', 'rolesRoleBody', 'rolesRoleDirty', 'renderRolesInto', 'wireRoles', 'openProfileTab', 'loadProfile', 'renderProfileInto', 'wireProfile', 'openConversation', 'wireDeviceOut', 'profileTwoFactor', 'pfTf', 'pfFresh', 'wireTwoFactor', 'openProfileTwoFactor', 'openAppsTab', 'loadApps', 'appsIntro', 'appsStatus', 'appsSection', 'renderAppsInto', 'devHow', 'devAppRow', 'renderFindingsInto', 'fxRows', 'fxFilter', 'fxBarHtml', 'fxBarBand', 'fxWireBar', 'reportAges', 'refresh', 'refreshSoon', 'renameProject', 'rnDialsHome', 'render',
  'idleSection', 'wireIdleSection', 'pathsSection', 'wirePathsSection', 'settingsSections', 'withRevert', 'tunnelSteps', 'tunnelStatus', 'tunnelNodes', 'wireSettingsSections', 'settingsLive',
    'reportsSection', 'clearReports',
  'renderDoc', 'renderDockerInto', 'renderGuarded', 'renderJobsInto', 'renderNodesInto', 'renderNotebookInto', 'renderSettingsInto',
  'renderToolchainsInto', 'renderProjectsInto', 'repoOfUrl',
  'reschedRevs', 'rnDrawAuth', 'rnDrawKey', 'rnKeyAct', 'drawSetup', 'setupFinish', 'setupNeeded', 'setupNode', 'setupOwn',
  'rnDrawPeople', 'rnDrawPrefs', 'rnFolds', 'rnTestAuth', 'rnLoadFtp', 'rnDrawReach', 'rnReachNodes', 'rnReachNow', 'rnReachSync', 'rnFtpWhere', 'rnDrawFtp', 'rnFtpChange', 'rnSaveFtp', 'rnFillNode', 'rnFillNodesMore', 'rnFillPrefs', 'rnFillPrefsRest', 'rnLoadAuth', 'rnLoadPeople', 'rnDrawGitPol', 'rnWhyOff', 'rnLoadSnapshots', 'rnDrawSnapshots', 'rnSavePeople', 'rnSessionEnd', 'rnSessionsDraw', 'rnSessionsLoad', 'rnFolderLine', 'ghName', 'rnShow', 'rnSubmit',
  'roomForTab', 'saveLayout', 'sendCode', 'sendKey',
  'sessionLabels', 'sessionOf', 'ask', 'askText', 'askYes', 'askQuestion', 'askYesWord', 'setArchived', 'setBadge', 'setLocked', 'setPinned',
  'setProjectPinned', 'shortUptime', 'shortUptime', 'shellCtx', 'show', 'showInStack', 'holdLeaving',
  'signIn', 'signOut', 'slideBody', 'slideDetails',
  'slideHidden', 'fadeIn', 'ghostOf', 'ghostOut', 'fadeThrough', 'slideMark', 'slidePanel', 'swapBox', 'startClaude', 'sendSure', 'launchClaude',   'openBrief', 'closeBrief', 'briefGo', 'pArchivePicked',
  'tabLabel', 'tabLabels', 'tabTitle', 'untitle', 'untitleIn', 'untitleWatch', 'helpToggle', 'cLock', 'dmUnrouted', 'nodeDoorConfig', 'nginxUndeployed', 'resumePicker', 'toggleBell', 'toggleUiMenu', 'unveil', 'watchSignin', 'wireConsole', 'wireLogSection', 'wireJobsTab', 'wireNodeConf', 'wireNodesTab', 'wireMacros',
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
                 'renderSessionsInto', 'drawBell', 'notify', 'openTrash', 'drawTrash',
                 'paint', 'drawUiMenu', 'toggleBell'];
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
const known = new Set(browserNames), uses = [], whose = new Map();
for (const s of scripts)
  traverse(babelParse(s.code, s.file.replace(/\.html$/, '.js'), false), {Program(p){
    Object.keys(p.scope.bindings).forEach(n => { known.add(n); whose.set(n, [...(whose.get(n) || []), s.file]); });
    for (const [n, node] of Object.entries(p.scope.globals))
      uses.push({n, at: `${s.file}:${s.base + (node.loc?.start.line || 0)}`});
    p.stop();
  }});
const stray = uses.filter(u => !known.has(u.n)).map(u => `${u.n} (${u.at})`);
ok(scripts.length > 2 && known.size > 500 && stray.length === 0,
   `every name the page's ${scripts.length} scripts use is declared by one of them or is the browser's${
     stray.length ? `; declared nowhere: ${stray.join(', ')}` : ''}`);

// One name, one script (B738). A `function` declared at the top level of two
// classic scripts is one global, and the later script's quietly replaces the
// earlier's: page-dock.js's placeTab took page-tabstrip.js's drag helper's
// name on 14 Oct, and only a suite's TypeError said so. (A `let` or `const`
// declared twice is a SyntaxError on load, which zero console errors holds.)
const twice = [...whose].filter(([, fs]) => fs.length > 1).map(([n, fs]) => `${n} (${fs.join(', ')})`);
ok(twice.length === 0,
   `no top-level name is declared by two scripts${twice.length ? `; declared twice: ${twice.join('; ')}` : ''}`);

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
