// The shared to-do list: the one surface here that both sides write.
//
// The operator adds an item in the panel, a session adds one through
// `bb roadmap`, and either can tick it off. The open items are appended to every
// Claude session bb-tty starts, which is the whole point: something noticed
// mid-task and left undone used to live in the conversation and die with it.
import { launch, newPage, ok, done, ready, animatedDuring, tmuxCapture, tmuxNew, tmuxKill, nbShown, nbGone, nbTab, patience, refreshUntil, holdPoll, freePoll, URL, DIR, closePage } from './lib.mjs';
// The add band unrolls the box in its place (R119 step 4): typing a line
// presses Add to roadmap first, as a person does.
const unroll = async pg => { if (await pg.$eval('#roadmapForm', f => f.hidden)) await pg.click('#roadmapShow'); };
import { readFileSync, existsSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// The checkout's bb, not the stub on the harness PATH: `bb roadmap` is the half
// of this a session uses, and it is the real implementation under test.
const BB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'bb');
const FILE = `${DIR}/state/roadmap.json`;
const read = () => existsSync(FILE) ? JSON.parse(readFileSync(FILE, 'utf8')) : { projects: {} };

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });

// A row's shelf, pencil and bin sit on the open row (R223): opened first,
// the way a thumb does, by its caret.
const rowOpen = async sel => {
  await page.evaluate(s => { const row = document.querySelector(s); const acts = row?.querySelector('.rowacts');
    if (acts?.hidden) row.querySelector('.dtog')?.click(); }, sel);
  await page.waitForTimeout(300);
};await page.goto(URL);
await ready(page);

const row = n => `.pgrid .pcard[data-row="${n}"]`;   // the project's card on the Projects page (R218 step 3)
// Nothing the panel does reaches disk until Save. Every assertion about the
// file goes through this, which is also the assertion that staging works.
const saveList = async () => {
  if (await page.$eval('#roadmapSaveQuiet', b => b.disabled)) return;
  await page.click('#roadmapSaveQuiet');
  await page.waitForFunction(() => {
    const b = document.getElementById('roadmapSaveQuiet');
    return b.getAttribute('aria-busy') !== 'true' && b.disabled; }, { timeout: 15000 });
};
const bbRoadmapEarly = (...a) => execFileSync(BB, ['roadmap', ...a],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/roadmap', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);
const open = () => page.$$eval('#roadmapList .roadmap', ts => ts.map(t => ({
  id: t.dataset.id, step: t.dataset.step, text: t.querySelector('.txt').textContent,
  sent: t.classList.contains('sent'),
  can: t.querySelector('.go').getAttribute('aria-disabled') !== 'true',
  sel: t.querySelector('.go').classList.contains('sel'),
  claude: !!t.querySelector('.who:not(.fin)') })));

// ---- adding ------------------------------------------------------------
// The row and its notebook icon went with R218 step 3: a project is a
// page, opened by its name on the Projects page or by openNotebook.

await page.evaluate(n => openNotebook(n), 'alpha');
await nbShown(page);
await nbTab(page, 'roadmap');
ok(await page.$eval('#memTitle', el => el.textContent === 'Notebook: alpha'),
   'the panel opens on the list');
await page.waitForFunction(() => document.getElementById('roadmapHint').textContent.length > 0);
ok((await page.$eval('#roadmapHint', el => el.textContent)) === 'nothing yet'
   && await page.$eval('#roadmapEmpty', el => !el.hidden && /every Claude session/.test(el.textContent)),
   '...and says where the items end up, as its empty state under a head that counts (R119 step 4)');

await unroll(page); await page.fill('#roadmapText', 'make the picker wrap properly');
await page.keyboard.press('Enter');
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap').length === 1);
let items = await open();
ok(items[0].text === 'make the picker wrap properly' && !items[0].claude,
   'Enter adds it, unmarked; this one is the operator\'s');
ok(await page.$eval('#roadmapText', el => el.value === ''),
   '...and the field clears for the next one');
// Staged, not written. The panel is a form with a Save button: three steps
// typed and looked at together, then kept or dropped as one.
ok(!(read().projects.alpha || []).length,
   '...but nothing is on disk yet: the panel writes on Save and not before');
ok(!await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   '...which is what arms Save');
// A locator, not $eval: $eval resolves once and throws if the row is not there
// at that instant, and this list repaints. Seen for real: a full run on 27 Aug
// died here with "Failed to find element matching selector" while the same run
// alone passed. A locator re-resolves until it is there or the timeout is.
ok((await page.locator('#roadmapList .roadmap[data-step="-1"] .n').first()
      .textContent({ timeout: patience(30000) })).trim() === 'new',
   '...and it wears "new" rather than a number, because it has not got one yet');
await saveList();
ok(read().projects.alpha.length === 1,
   'Save writes it, into /config and not into the project');


// ---- what a session adds is marked -------------------------------------
// Through bb, the same way a session would: one file, two writers.
execFileSync(BB, ['roadmap', 'add', 'delete a project from the dashboard'],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap').length === 2);
items = await open();
const mine = items.find(i => i.text.includes('delete a project'));
ok(mine && mine.claude,
   'an item a session added through bb roadmap shows up, marked as Claude\'s');
ok(items.filter(i => i.claude).length === 1,
   '...and the operator\'s own is not');
// At the end, not the top. The number on a row is the item's own id, so the
// list only reads in order if new ones go on the bottom; otherwise every
// addition renumbers the rows above it and "#3" stops meaning anything.
const wasAt = items.findIndex(i => i.id === mine.id);
ok(wasAt === items.length - 1,
   '...at the end of the list, where its number follows the one above it');
ok(await page.$$eval('#roadmapList .roadmap[data-step="-1"] .n',
     ns => ns.map(n => +n.textContent.slice(1)).every((v, i, a) => !i || v > a[i - 1])),
   '...and the numbers on the rows run down the page');

// A long line lands in claude's input box folded into "[Pasted text #1]":
// the TUI reads a burst of typed characters as a paste, so the words never
// echo and a step of a few hundred characters was reported typed but not
// sent while sitting in the box whole. The placeholder counts as the echo.
// notify.tell against a stand-in tmux, since no fixture here folds a paste.
{
  const out = execFileSync('python3', ['-c', `
import sys; sys.path.insert(0, ${JSON.stringify(join(dirname(fileURLToPath(import.meta.url)), '..'))})
import notify
# The box shows the placeholder once the line is typed, and not before: a
# stand-in that moved on with every look read as a pane still drawing,
# which tell now waits out before it counts (B389).
typed = []
calls = []
def run(argv, timeout=10):
    calls.append(argv)
    if argv[1] == 'capture-pane':
        return {"code": 0, "out": '> [Pasted text #1]' if typed else '> '}
    if argv[1] == 'send-keys' and '-l' in argv:
        typed.append(1)
    return {"code": 0, "out": ""}
notify.configure(run=run)
notify.SETTLE = 0
r = notify.tell('claude-x', 'a step of ' + 'many words ' * 40, ['claude-x'])
print(r.get('sent'), sum(1 for c in calls if c[1] == 'send-keys' and c[-1] == 'Enter'))
`], { encoding: 'utf8' }).trim();
  ok(out === 'True 1', `a line the box folded into a paste placeholder counts as arrived, and Enter follows (${out})`);
}

// ---- sending -----------------------------------------------------------
// The fixture's claude-alpha is a plain shell, which is what makes this
// testable: a shell echoes what is typed into it, which is the exact property
// notify.py uses to decide that Enter is safe.
ok(items.every(i => i.can), 'with a session running, the arrows are live');
// An arrow arms Send; it does not fire it. Sending does four things at once
// (the line goes, the step is crossed off, the panel closes and you land in
// that tab), and one tap for all four is a mis-tap you cannot take back.
ok(await page.$('.sendbox') === null,
   'with nothing armed there is no send box at all');
// The box unrolls rather than appearing, on the same height tween the folds
// use, so the lines under it ride down instead of jumping out of the way.
const armed = await animatedDuring(page, async () => {
  await page.click(`#roadmapList .roadmap[data-id="${mine.id}"] .go`);
  await page.waitForSelector('.sendbox');
});
ok(armed.some(k => k.includes('sendbox')), 'arming an arrow unrolls the box');
ok((await open()).find(i => i.id === mine.id).sel,
   'picking an arrow highlights it; that is the whole confirmation');
// ...once. It is rebuilt on every draw, and a poll landing while it is open
// must not replay the arrival.
const reArmed = await animatedDuring(page, () => page.evaluate(() => refresh()));
ok(!reArmed.some(k => k.includes('sendbox')),
   '...and a redraw underneath it does not play that again');
// Under the row it would send, not at the foot of the panel: the confirmation
// for handing a line over belongs beside the line, which on a phone is the
// difference between reading it and scrolling for it.
ok(await page.$eval('.sendbox', b =>
     b.previousElementSibling?.classList.contains('roadmap')
     && b.previousElementSibling.dataset.id === b.closest('.grp')
          .querySelector('.roadmap').dataset.id),
   '...and the box opens directly under that row');
ok(await page.$('#roadmapAlso') === null,
   '...and asks nothing about saving, because nothing can be unsaved by here');
await page.click(`#roadmapList .roadmap[data-id="${mine.id}"] .go`);
await page.waitForFunction(() => !document.querySelector('.sendbox'));
ok(!(await open()).find(i => i.id === mine.id).sel,
   'picking it again puts it down');
ok(!read().projects.alpha.find(r => String(r.id) === mine.id).sent,
   '...having sent nothing');

await page.click(`#roadmapList .roadmap[data-id="${mine.id}"] .go`);
await page.waitForSelector('.sendbox');
// Model and effort are not questions in this box and are not applied by it:
// they are the project's own setting, applied when its session starts.
ok(await page.$('#sendModelSel') === null && await page.$('#sendNote') === null,
   'no pickers here, and nothing about switching either');
// The note field rides with the step on the same line, so a session gets one
// message rather than a step and then an afterthought glued behind it.
await page.fill('#sendMore', 'the select is the one on the left');
await page.click('#roadmapGo');
// Three things: the line goes, the step is crossed, and the session's tab
// opens. The notebook stays where it is: it is a tab now, and a tab is not
// in the way of the one you are being sent to.
await page.waitForFunction(() => [...document.querySelectorAll('#pane1 .dtab')]
  .some(t => /Claude: alpha/.test(t.textContent)), { timeout: 20000 });
ok(read().projects.alpha.find(r => String(r.id) === mine.id).sent > 0,
   'sending crosses it off; the record is what was handed over');
const pane = tmuxCapture('claude-alpha');
ok(pane.includes('delete a project from the dashboard'),
   '...because it really went into the session');
ok(/\(Also: the shared to-do list/.test(pane),
   '...with the note about the other changes on the same line, not racing it');
ok(/From the operator, with this step: the select is the one on the left/.test(pane),
   '...and the operator\'s own note with it, on that same line too');
const flags = read().unsaved?.alpha || {};
ok(flags.roadmap === false && flags.memory === false,
   '...and the panel counts as told, since it was told');
ok(await page.$$eval('#pane1 .dtab', ts => ts.some(t => /Claude: alpha/.test(t.textContent))),
   '...and it put the session\'s tab in the dock');

// Back in, for the rest.
await page.evaluate(n => openNotebook(n), 'alpha');
await page.waitForSelector('#roadmapList .roadmap', { timeout: 20000 });
items = await open();
const still = items.find(i => i.id === mine.id);
ok(still.sent && still.can,
   '...and it stays, struck through, and still live, because "it did not '
   + 'take, do it again" is a real answer and the strike is the record of the '
   + 'first go rather than a lock on the second');
ok(items.findIndex(i => i.id === mine.id) === wasAt,
   '...in the place it was, because the order is the record');

// ---- nothing is switched on the way in ----------------------------------
// Model and effort used to be typed here as claude's own slash commands,
// because a running session cannot be changed by a flag it was not started
// with. That stopped working the day /model grew a confirmation: the step
// went into the dialog. They are the project's setting now, applied by bb-tty
// at launch, so a send is only ever the step. The fixture's session is a
// shell, so what lands in the pane is the literal text, which is what makes
// "no slash command, ever" checkable at all.
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', 'C-u']);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', '-l', '--', 'clear']);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', 'Enter']);
await page.evaluate(async () => {
  await fetch('/api/prefs', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', model: 'sonnet', effort: 'xhigh' }) });
});
await page.evaluate(n => openNotebook(n), 'alpha');
await page.waitForSelector('#roadmapList .roadmap', { timeout: 20000 });
await page.click(`#roadmapList .roadmap[data-id="${mine.id}"] .go`);
await page.waitForSelector('.sendbox');
await page.click('#roadmapGo');
await page.waitForFunction(() => !document.querySelector('.sendbox'),
                           null, { timeout: 20000 });
const sent = tmuxCapture('claude-alpha');
ok(!/\/model/.test(sent) && !/\/effort/.test(sent),
   'a send types no slash command, even with a model set for the project');
ok(/delete a project/.test(sent), '...and the step itself goes on its own');
// Back into the notebook: sending lands you in the session's tab, and what
// follows is about the panel.
await page.evaluate(n => openNotebook(n), 'alpha');
await page.waitForSelector('#roadmapList .roadmap', { timeout: 20000 });

// ---- unsaved work blocks a send, and does not follow you to another tab --
// Two rules with one reason: a step is a line typed into a session, and the
// session then goes and reads the list. Handing over a step the server has
// never heard of, off a list that only exists in this browser, is how the two
// end up describing different plans.
const tab = v => `.nbtabs button[data-v="${v}"]`;
await unroll(page); await page.fill('#roadmapText', 'staged, deliberately not saved');
await page.click('#roadmapAdd');
await page.waitForFunction(() => [...document.querySelectorAll('#roadmapList .txt')]
  .some(t => t.textContent.includes('staged, deliberately')));
ok(await page.$$eval('#roadmapList .roadmap .go', gs => gs.every(g => g.getAttribute('aria-disabled') === 'true')),
   'an unsaved change puts every arrow down');
ok(/not saved/.test(await page.$eval('#roadmapHint', h => h.textContent)),
   '...and the line above the list says which, and what to do about it');
ok((await page.$eval('#roadmapList .roadmap .go', g => saidOf(g))).includes('save or revert'),
   '...and so does the arrow itself');
// dispatched rather than clicked: a real click cannot reach a disabled
// button, and what wants proving is that even one that did lands nowhere.
await page.dispatchEvent(`#roadmapList .roadmap[data-id="${mine.id}"] .go`, 'click');
await page.waitForTimeout(200);
ok(await page.$('.sendbox') === null,
   '...and no box opens, because there is nothing it could honestly send');

const nd = page.dialogs.length;
await page.click(tab('briefing'));
await page.waitForFunction(() => !document.querySelector('[data-view="briefing"]').hidden,
                           null, { timeout: 15000 });
ok(page.dialogs.length === nd + 1 && /thrown away/.test(page.dialogs.at(-1)),
   'leaving the tab asks before throwing the unsaved change away');
ok(!read().projects.alpha.some(r => /staged, deliberately/.test(r.text)),
   '...and it never reached disk, which is what "unsaved" meant');
await page.click(tab('roadmap'));
await page.waitForFunction(() => !document.querySelector('[data-view="roadmap"]').hidden);
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap').length > 0);
ok(!(await open()).some(i => /staged, deliberately/.test(i.text)),
   '...and coming back, the change is gone rather than waiting where it was left');
ok((await open()).some(i => i.can),
   '...so the arrows are live again');

// ---- what a session is told --------------------------------------------
// Counts and the verbs (R202): the list itself is a `bb roadmap` away, and
// the items a prompt names arrive on that prompt (preamble.mjs).
const prompt = execFileSync(BB, ['roadmap', '--prompt'],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(/\d+ open items?/.test(prompt) && /bb roadmap show R4/.test(prompt) && !prompt.includes('make the picker wrap properly'),
   'the block a session is started with counts the open items and says how to read one, and carries no list');

// ---- an order that matters ---------------------------------------------
// A change needing three things done in sequence is one item with steps, not
// three items that can be handed over backwards.
execFileSync(BB, ['roadmap', 'add', 'rework the picker',
                  '--step', 'widen the select', '--step', 'then re-measure it'],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap[data-step="1"]').length === 1);
// A group is a fold now (the operator, 29 Sep): its row is the summary and
// its steps open under it on a tap. Checked once, then every group is
// opened as it is drawn, since the rest of this file reaches into steps.
{
  await page.waitForSelector('#roadmapList details.grp:has(.roadmap[data-step="1"])', { timeout: 15000 });
  const first = await page.$eval('#roadmapList details.grp:has(.roadmap[data-step="1"])', d => ({ open: d.open, steps: d.querySelectorAll('.roadmap[data-step]:not([data-step="-1"])').length,
    shown: [...d.querySelectorAll('.roadmap[data-step]:not([data-step="-1"])')].some(r => r.checkVisibility()) }));
  ok(!first.open && !first.shown, `a group starts folded, its steps out of sight (${JSON.stringify(first)})`);
  // The send is the Claude mark among the row's own buttons on the right,
  // the caret is where the arrow was, and the words open the fold (the
  // pencil rewords a group).
  const shape = await page.$eval('#roadmapList details.grp:has(.roadmap[data-step="1"]) > summary .roadmap', r => {
    const kids = [...r.children].map(e => e.className.split(' ')[0]);
    return { kids, goHasMark: !!r.querySelector('.go svg'), noBox: !r.querySelector('.rwbox, textarea') };
  });
  ok(shape.kids[0] === 'eye' && shape.kids.indexOf('body') < shape.kids.indexOf('eye', 1) && shape.goHasMark,
     `the group row leads with the fold's caret, its words, then Send to Claude first among its buttons (${shape.kids.join(' ')})`);
  await page.click('#roadmapList details.grp:has(.roadmap[data-step="1"]) > summary .txt');
  await page.waitForFunction(() => document.querySelector('#roadmapList details.grp:has(.roadmap[data-step="1"])').open, null, { timeout: 5000 });
  ok(await page.$eval('#roadmapList details.grp:has(.roadmap[data-step="1"])', d => d.open && !d.querySelector('textarea')
       && [...d.querySelectorAll('.roadmap[data-step]:not([data-step="-1"])')].every(r => r.checkVisibility())),
     '...and a tap on its words opens every step under it rather than a reword box');
  await page.evaluate(() => new MutationObserver(() => document.querySelectorAll('#roadmapList details.grp:not([open])').forEach(d => { d.open = true; }))
    .observe(document.getElementById('roadmapList'), { childList: true, subtree: true }));
  await page.evaluate(() => document.querySelectorAll('#roadmapList details.grp:not([open])').forEach(d => { d.open = true; }));
}
items = await open();
const g = items.find(i => i.text === 'rework the picker');
const s1 = items.find(i => i.text === 'widen the select');
const s2 = items.find(i => i.text === 'then re-measure it');
ok(g.can, 'a group\'s own arrow stands for its next step');
ok(s1.can && !s2.can,
   'only the next step in line can be sent; the one after it is dead');

await post({ action: 'send', project: 'alpha', id: Number(s1.id), step: 0 });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="0"]`)?.classList.contains('sent'),
  s1.id, { timeout: 15000 });
items = await open();
ok(items.find(i => i.text === 'then re-measure it').can,
   'sending the first opens the second, and only then');
ok(items.find(i => i.text === 'widen the select').can,
   '...and the one that went can go again, which is what a step that quietly '
   + 'did not happen needs');
ok(items.findIndex(i => i.text === 'widen the select')
   < items.findIndex(i => i.text === 'then re-measure it'),
   '...and nothing moved');

// A step arrives on its own, and "then re-measure it" means nothing without
// the plan it belongs to, so the line carries all three: that it is one step
// of several, what the whole thing is for, and which step this is.
const stepLine = tmuxCapture('claude-alpha');
ok(/step 1 of 2 in a plan/i.test(stepLine)
   && /The plan: rework the picker/.test(stepLine)
   && /Step 1: widen the select/.test(stepLine),
   'a step is sent with the plan around it, not on its own');

const skip = await post({ action: 'send', project: 'alpha', id: Number(s2.id), step: 1 });
ok(skip.status === 200, 'the second can now be sent');
const back = await post({ action: 'send', project: 'alpha', id: Number(s1.id), step: 0 });
ok(back.status === 200, 'and the first again through the API: "it did not take" '
   + 'is a real answer, it just costs an uncross on screen');
page.errors = [];

// ---- crossing off by hand ----------------------------------------------
// The other way a line gets struck: the operator did it themselves, or it
// turned out not to be needed. Same mark, so the group moves on either way,
// which is the point, because otherwise a step you handled yourself blocks
// every step behind it forever.
items = await open();
const c1 = items.find(i => i.text === 'widen the select');
const c2 = items.find(i => i.text === 'then re-measure it');
await post({ action: 'cross', project: 'alpha', id: Number(c1.id), step: 0, on: false });
await post({ action: 'cross', project: 'alpha', id: Number(c2.id), step: 1, on: false });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => !document.querySelector(
  '#roadmapList .roadmap[data-step="0"]')?.classList.contains('sent'));
items = await open();
ok(!items.find(i => i.text === 'then re-measure it').can,
   'with both steps back open, only the first can go again');
ok((await open()).find(i => i.step === '-1'
     && i.text === 'rework the picker').can,
   '...and the group\'s own arrow stands for it');
await page.click(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="-1"] .go`);
await page.waitForSelector('.sendbox');
items = await open();
ok(items.find(i => i.text === 'rework the picker').sel
   && items.find(i => i.text === 'widen the select').sel
   && !items.find(i => i.text === 'then re-measure it').sel,
   'picking the group lights the group and its next step, and nothing else');
await page.click(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="-1"] .go`);
await page.waitForFunction(() => !document.querySelector('.sendbox'));

// ---- the shelf -----------------------------------------------------------
// The state between "do this" and "we are not doing this". It is an item's
// business, never a step's: parking one step of a plan and leaving the rest
// live is not a state a plan can be in, so a group is shelved whole.
const shelves = () => page.$$eval('#roadmapList .roadmap',
  ts => ts.filter(t => t.querySelector('.x')).map(t => t.dataset.step));
ok((await shelves()).every(st => st === '-1'),
   'only items carry a shelf button, never a step of a plan');

await rowOpen(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="-1"]`);

await page.click(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="-1"] .x`);
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .grp:has(.roadmap[data-id="${id}"])`)?.classList.contains('shelved'),
  c1.id, { timeout: 10000 });
items = await open();
ok(items.filter(i => i.id === c1.id).every(i => !i.can),
   'shelving kills every arrow in the group, its steps included');
await saveList();
ok(read().projects.alpha.at(-1).text === 'rework the picker',
   '...and sinks it to the bottom of the list, where what is not live belongs');
const shelvedPrompt = execFileSync(BB, ['roadmap', '--prompt'],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
// A state dir this copy cannot write (a checkout's bb on a node, B228):
// the list still prints and the exit is clean; marking it read is a
// courtesy, not the point.
const unwritable = execFileSync(BB, ['roadmap'],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: '/proc/bb-no-such-state',
           WORKSPACE: `${DIR}/ws` }, stdio: ['ignore', 'pipe', 'pipe'] }).toString();
ok(!/Traceback|PermissionError/.test(unwritable),
   'bb roadmap on a state dir it cannot write prints the list and exits clean');
ok(/and \d+ parked by the operator/.test(shelvedPrompt) && !/rework the picker/.test(shelvedPrompt),
   '...and a session is told how many are parked, and never a parked title (R202)');
const up = await post({ action: 'move', project: 'alpha', id: Number(c1.id), dir: -1 });
ok(up.status === 400 && /stay at the bottom/.test(up.body.error),
   '...and it cannot be shuffled back up among the live ones');
page.errors = [];

await rowOpen(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="-1"]`);

await page.click(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="-1"] .x`);
await page.waitForFunction(id => !document.querySelector(
  `#roadmapList .grp:has(.roadmap[data-id="${id}"])`)?.classList.contains('shelved'),
  c1.id, { timeout: 10000 });
// Saved before asking whether it is live: taking something off the shelf is
// itself an unsaved change, and an unsaved change puts every arrow down.
await saveList();
ok((await open()).find(i => i.id === c1.id && i.step === '-1').can,
   'the same button takes it off the shelf: the one control here that undoes '
   + 'itself, which is the whole difference between it and the bin');

// Every row has a bin. It was the head of the queue only, on the theory that
// things come off a plan from the front, but that cost steps one and two to
// reach a stale step three, and the order that actually matters is the order
// things are *sent* in, which the frontier rule protects on its own.
const bins = () => page.$$eval('#roadmapList .roadmap',
  ts => ts.filter(t => t.querySelector('.rm')).map(t => t.dataset.step));
const allRows = await page.$$eval('#roadmapList .roadmap', ts => ts.length);
ok((await bins()).length === allRows,
   `anything can be dropped, step or item: ${allRows} rows, ${
     (await bins()).length} bins`);
ok((await bins()).includes('1'),
   '...including a step in the middle of a plan, which used to need the two '
   + 'in front of it deleted first');

// ---- dropping one step out of a plan -----------------------------------
// With the reason it went. Nothing here can be undone, so the note is the
// only thing standing between a dropped line and somebody adding it back,
// and it is optional, because a reason demanded is a reason typed as "x".
await rowOpen(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="0"]`);
await page.click(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="0"] .rm`);
await page.waitForSelector('.dropbox', { timeout: 10000 });
ok(await page.$$eval('#roadmapList .roadmap', ts => ts.length) > 0
   && read().projects.alpha.find(r => String(r.id) === c1.id).steps.length === 2,
   'the bin asks in place, and nothing has gone while it is asking');
ok(await page.evaluate(() => document.activeElement?.tagName !== 'INPUT'),
   '...without the cursor in the field, like every other box in this window');
await page.click('.dropbox .stop');
// Waited for rather than read in the same breath as the click, which a
// loaded box lost once (B292); a Cancel that never closes the box still
// fails here, five seconds on, and the line says which half it was.
{
  const shut = await page.waitForSelector('.dropbox', { state: 'detached', timeout: 5000 })
    .then(() => true, () => false);
  const steps = read().projects.alpha.find(r => String(r.id) === c1.id).steps.length;
  ok(shut && steps === 2,
     `Cancel closes it and drops nothing (the box ${shut ? 'closed' : 'is still open'}, ${steps} steps on disk)`);
}

await rowOpen(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="0"]`);

await page.click(`#roadmapList .roadmap[data-id="${c1.id}"][data-step="0"] .rm`);
await page.waitForSelector('.dropbox textarea', { timeout: 10000 });
await page.fill('.dropbox textarea', 'the select is gone, nothing to widen');
await page.click('.dropbox .danger');
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap[data-step="0"]').length === 1
  && document.querySelectorAll('#roadmapList .roadmap[data-step="1"]').length === 0,
  { timeout: 10000 });
ok(read().projects.alpha.find(r => String(r.id) === c1.id).steps.length === 2,
   '...and it is off the screen before it is off the disk, like every other '
   + 'change the panel makes');
await saveList();
items = await open();
ok(!items.some(i => i.text === 'widen the select')
   && items.some(i => i.text === 'then re-measure it'),
   'a step can be dropped out of a group on its own');
ok(items.find(i => i.text === 'then re-measure it').can,
   '...and what was behind it becomes the next in line');
ok(read().projects.alpha.find(r => String(r.id) === c1.id).steps.length === 1,
   '...leaving the rest of the plan intact');
ok(bbRoadmapEarly('history', '--find', 'nothing to widen')
     .includes('why: the select is gone, nothing to widen'),
   '...and the reason it went is in the log, findable by its own words');

// ---- a session correcting a plan ---------------------------------------
// A plan written last week can describe a design that has since moved.
// Correcting it beats working around it, so the CLI a session drives can
// reword an item and add, reword or drop a single step of one.
const bbRoadmap = bbRoadmapEarly;
const grp = () => read().projects.alpha.find(r => String(r.id) === String(c1.id));
bbRoadmap('edit', c1.id, 'rework the picker, properly this time');
ok(grp().text === 'rework the picker, properly this time',
   'bb roadmap edit rewords an item');
bbRoadmap('step', 'add', c1.id, 'and check it on a phone');
ok(grp().steps.length === 2 && grp().steps[1].text === 'and check it on a phone',
   'bb roadmap step add gives an existing item another step');
bbRoadmap('step', 'edit', c1.id, '2', 'and check it at both sizes');
ok(grp().steps[1].text === 'and check it at both sizes',
   'bb roadmap step edit rewords one step, numbered the way a human reads it');
bbRoadmap('step', 'rm', c1.id, '2');
ok(grp().steps.length === 1, 'bb roadmap step rm drops one step and leaves the rest');

// A session can move an item as well as a step: both halves of restructuring,
// because it is the one that knows a plan has to happen before the item under
// it. And it can shelve, but only in one direction: taking something off the
// shelf reverses a decision it was not told the reason for.
const orderNow = () => read().projects.alpha.map(r => String(r.id));
const wasOrder = orderNow();
bbRoadmap('mv', c1.id, 'up');
ok(orderNow().indexOf(c1.id) === wasOrder.indexOf(c1.id) - 1,
   'bb roadmap mv moves an item up the list');
bbRoadmap('mv', c1.id, 'down');
ok(JSON.stringify(orderNow()) === JSON.stringify(wasOrder), '...and back down');
bbRoadmap('shelve', c1.id);
ok(read().projects.alpha.at(-1).shelved, 'bb roadmap shelve parks one');
// ...and asking for it back is a request (R78): held for a person on the
// project with its reason, the item still shelved until they answer. The
// pending suite walks the approval; here the ask and the hold.
ok(/asked to take R\d+ off the shelf: held for approval on the notebook/.test(bbRoadmap('unshelve', c1.id, 'the blocker is gone'))
   && read().projects.alpha.at(-1).shelved,
   '...and a session asking to unshelve is held for approval, the item still shelved');
await post({ action: 'shelve', project: 'alpha', id: Number(c1.id), on: false });

// ---- batches -------------------------------------------------------------
// Working something out is arriving at one decision, not making a series of
// them. The list still moves as the work happens (hiding it would be worse
// than a noisy log), but the record is written once, at commit.
bbRoadmap('begin');
bbRoadmap('edit', c1.id, 'a first attempt at the wording');
bbRoadmap('edit', c1.id, 'a second attempt');
bbRoadmap('edit', c1.id, 'what it should have said all along');
ok(read().projects.alpha.find(r => String(r.id) === c1.id).text
   === 'what it should have said all along',
   'a batch does not hide the work; the list moves as it is made');
ok(/batch open/.test(bbRoadmap()),
   '...and says so at the top of the list, so it cannot be left open unnoticed');
const beforeCommit = bbRoadmap('history', '-n', '30');
ok(!/a second attempt/.test(beforeCommit),
   '...while writing nothing to the log yet');
const done1 = bbRoadmap('commit');
ok(/1 entry, 2 folded/.test(done1),
   'commit folds three rewordings of one line into the one that happened');
// Found rather than counted to: several of these land in the same second, so
// "the last three" is not a stable way to ask for one of them.
const afterCommit = bbRoadmap('history', '--find', 'attempt');
ok(!afterCommit.includes('a second attempt')
   && !afterCommit.includes('a first attempt'),
   '...and the attempts it discarded are not in the log at all');
ok(/what it should have said all along/.test(
     bbRoadmap('history', '--find', 'should have said')),
   '...only the wording it ended on');

bbRoadmap('begin');
bbRoadmap('add', 'something it thought better of');
bbRoadmap('edit', c1.id, 'mangled again');
bbRoadmap('revert');
ok(!read().projects.alpha.some(r => r.text === 'something it thought better of')
   && read().projects.alpha.find(r => String(r.id) === c1.id).text
      === 'what it should have said all along',
   'revert puts the list back exactly as the batch found it');
ok(!/mangled again/.test(bbRoadmap('history', '-n', '10')),
   '...and writes nothing at all');

bbRoadmap('begin');
bbRoadmap('edit', c1.id, 'the session was mid-thought');
await post({ action: 'add', project: 'alpha', text: 'and the operator typed this' });
ok(/and the operator typed this/.test(bbRoadmap('history', '-n', '5')),
   'a change the operator makes while a batch is open is logged straight away, '
   + 'not swept into somebody else\'s batch');
const refused = (() => { try { return bbRoadmap('revert'); }
                         catch (e) { return String(e.stderr || e); } })();
ok(/operator has changed this list/.test(refused),
   '...which is what lets revert refuse rather than undo their work too');
bbRoadmap('commit');
await post({ action: 'remove', project: 'alpha',
             id: read().projects.alpha.find(r => r.text === 'and the operator typed this').id });

// ---- one batch over the whole notebook ----------------------------------
// A plan usually moves because of what the tracker now says, so the two are
// one transaction: committing the roadmap while reverting the tracker would
// leave a list describing work against a tracker that never recorded why.
const bbBug = (...a) => execFileSync(BB, ['bug', ...a],
  { env: { ...process.env, BB_BUG_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
const bugsFile = () => JSON.parse(readFileSync(`${DIR}/state/bugs.json`, 'utf8'));

bbRoadmap('begin');
ok(/batch open/.test(bbBug()),
   'a batch opened on the roadmap says so on the tracker too; it is one notebook');
bbBug('add', 'filed while the batch was open', '--sev', 'low');
bbRoadmap('add', 'and a plan to go with it');
const staged = bugsFile().projects.alpha.some(b => /filed while the batch/.test(b.title));
ok(staged, '...and the tracker moves as the work happens, the same as the list');
ok(!/filed while the batch/.test(bbBug('history', '-n', '20')),
   '...while its log waits for the commit, the same as the list\'s');
bbRoadmap('revert');
ok(!bugsFile().projects.alpha.some(b => /filed while the batch/.test(b.title))
   && !read().projects.alpha.some(r => /a plan to go with it/.test(r.text)),
   'reverting from the roadmap takes the tracker back with it');

// ...and it works from either name, because it is the same batch.
bbBug('begin');
bbBug('add', 'this one is kept', '--sev', 'medium');
bbBug('note', String(bugsFile().projects.alpha.at(-1).id), 'a first thought');
bbBug('note', String(bugsFile().projects.alpha.at(-1).id), 'a second thought');
const bugCommit = bbBug('commit');
ok(/entr/.test(bugCommit) && /folded/.test(bugCommit),
   'bb bug commit closes the same batch, folding the notes into the filing');
const bugLog = bbBug('history', '-n', '20');
ok(/this one is kept/.test(bugLog) && !/a first thought/.test(bugLog),
   '...so the log says it was filed, not that it was thought about three times');

// ---- the history --------------------------------------------------------
// Two people write this list and it only ever shows the present tense, so
// "was that step always worded like that?" had no answer. Now every change
// carries who made it and when, and since removing is the only way a line
// leaves, the log is what keeps a deletion from being final.
await page.evaluate(() => notebooks.get('alpha').reload());
await page.click('#roadmapLog');
await page.waitForFunction(() => document.querySelectorAll('#roadmapHist .hist').length > 0,
                           { timeout: 10000 });
const log = await page.$$eval('#roadmapHist .hist', hs => hs.map(h => ({
  when: h.querySelector('.when').textContent.trim(),
  act: h.querySelector('.act').textContent.trim(),
  was: h.querySelector('.was')?.textContent.trim() || '',
  by: h.querySelector('.who')?.textContent.trim() || '',
  what: h.querySelector('.what').textContent.replace(/\s+/g, ' ').trim() })));
ok(log.length > 1 && log.every((e, i) => !i || e.when <= log[i - 1].when),
   'the log opens newest first');
ok(log.some(e => e.act === 'dropped a step'
                 && /and check it at both sizes/.test(e.what)),
   '...and carries the words of what was dropped, which is the point of it');
ok(/\d{1,2}\s*\w+.*\d{2}:\d{2}/.test(log[0].when),
   '...with the date and the time on every line');
ok(log.every(e => /^(claude|you)( · \S+)?$/.test(e.by)),
   '...and who did it on every line, which is the half neither of you can '
   + 'reconstruct afterwards');
// ...and WHICH person. "you" says a person rather than a session, which was
// the whole answer while there was one account; the name is what tells two
// of them apart, and a session carries its account's because a session has
// an author too. The audit on the Nodes tab has done this since accounts
// existed, and the notebook's four logs had not.
ok(log.some(e => e.by === 'you · test') && log.some(e => e.by === 'claude · test'),
   '...naming the account behind it, for a person and for a session alike');
ok(log.some(e => e.act === 'reworded'
                 && /rework the picker, properly/.test(e.what)
                 && e.was === 'rework the picker'),
   'a reword carries both wordings: the new one, and the old one struck through');
ok(log.some(e => e.act === 'dropped' || e.act === 'dropped a step'),
   '...and so is every drop, which is what makes the bin recoverable by hand');
ok(log.some(e => e.act === 'added' && /make the picker wrap properly/.test(e.what)
                 && e.by.startsWith('you')),
   'the operator\'s own additions are in it too, marked as theirs');
ok(log.some(e => e.act === 'sent'),
   '...and so is every handover, which is the record of what a session was asked');

// Narrowing it, because a session reading this pays for every line of it and
// the operator scrolling a phone pays too. The search reads the words, what a
// line used to say, and the reason it went.
await page.fill('#histFind', 'nothing to widen');
await page.waitForFunction(() => document.querySelectorAll('#roadmapHist .hist').length === 1,
                           { timeout: 10000 });
ok(await page.$eval('#roadmapHist .hist .note', n => /nothing to widen/.test(n.textContent)),
   'searching finds a line by the reason it was dropped, not just by its words');
await page.fill('#histFind', 'rework the picker');
await page.waitForFunction(() => document.querySelectorAll('#roadmapHist .hist').length > 1,
                           { timeout: 10000 });
ok(true, '...and by its words');
await page.fill('#histFind', 'zzz nothing at all');
await page.waitForFunction(() => /matches that/.test(
  document.getElementById('roadmapHist').textContent), { timeout: 10000 });
ok(true, '...and says so plainly when nothing does');
await page.fill('#histFind', '');
await page.selectOption('#histN', '25');
await page.waitForFunction(() => document.querySelectorAll('#roadmapHist .hist').length > 1,
                           { timeout: 10000 });
const capped = await page.$$eval('#roadmapHist .hist', hs => hs.length);
ok(capped <= 25, `the window caps what comes back (${capped} of them)`);
// A wait on the answer, not a half-second sleep: under a loaded whole run
// the list was read mid-redraw with fewer lines than it ends with (B413).
const answered = page.waitForResponse(r => /"action":"history"/.test(r.request().postData() || ''),
                                      { timeout: 15000 });
await page.selectOption('#histWhen', '0');
await answered;
const widened = await page.waitForFunction(n => document.querySelectorAll('#roadmapHist .hist').length >= n,
                                           capped, { timeout: 10000 }).then(() => true, () => false);
ok(widened, '...and widening it to all time brings back at least as much');

// It opens OVER the list rather than in place of it: the line you wanted to
// read the log against is still there behind, and the send box is put away
// only because a send aimed at a list you are reading about is not the
// gesture you meant.
ok(!await page.$eval('#roadmapList', el => el.hidden)
   && await page.$eval('#roadmapHist', el => el.closest('.sheetslot') !== null)
   && await page.$('.sendbox') === null,
   'the log opens over the list, with the list still behind it');
await page.click('#sheetClose');
await page.waitForFunction(() => document.querySelector('.nbsheet').hidden,
                           { timeout: 10000 });
ok(await page.$eval('#roadmapHist', el => el.hidden && el.closest('.sheetslot') === null)
   && await page.$eval('#roadmapLog', b => !b.classList.contains('on')),
   'and Close puts it back where it came from, and un-presses History');

// ---- a session mid-batch holds the operator's Save -----------------------
// Not the other way round: the panel is a copy of the list taken when it was
// opened, and replaying edits onto a list that has moved underneath is how
// two writers lose each other's work. Nothing here blocks the session, which
// cannot see this panel and should not be waiting on it.
bbRoadmap('begin');
await page.evaluate(() => refresh());
await page.waitForFunction(() => !document.getElementById('roadmapBatch').hidden,
                           { timeout: 20000 });
const banner = () => page.$eval('#roadmapBatch',
  el => el.textContent.replace(/\s+/g, ' ').trim());
ok(/is changing this\s+notebook/.test(await banner()),
   'the notebook says a session is mid-change, without being touched');
ok(await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   '...and Save is held while it is');
await unroll(page); await page.fill('#roadmapText', 'typed while a session was mid-batch');
await page.keyboard.press('Enter');
await page.waitForFunction(() => [...document.querySelectorAll('#roadmapList .txt')]
  .some(t => /typed while a session/.test(t.textContent)), { timeout: 10000 });
ok(await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   '...so typing is allowed and only committing it is not');
ok(!await page.$eval('#roadmapRevert', b => b.disabled),
   '...and Revert still works, since throwing away your own work depends on '
   + 'nobody else');
// The hold is the notebook's, not one tab's: a bug report posted while a
// session is mid-batch is refused at the click, with the banner as the why.
ok(await page.evaluate(() => document.querySelector('.pane .nb').classList.contains('held')),
   '...and the whole notebook wears the held state, memory and bugs included');
bbRoadmap('add', 'and the session was not blocked at all');
ok(read().projects.alpha.some(r => r.text === 'and the session was not blocked at all'),
   'the session writes straight through; the block is one-way');

// "Check now" answers "is it done yet?" without waiting for the poll. Here
// the batch is still open, so the answer is no and the guard stays.
await page.click('#roadmapRecheck');
await page.waitForFunction(() => document.getElementById('roadmapRecheck')
  && !document.getElementById('roadmapRecheck').disabled, { timeout: 15000 });
ok(await page.evaluate(() => nbHeldFor('alpha')),
   'Check now while the batch is still open leaves the guard in place');

bbRoadmap('commit');
await page.evaluate(() => refresh());
await page.waitForFunction(() => /A session finished changing this notebook/.test(
  document.getElementById('roadmapBatch').textContent.replace(/\s+/g, ' ')),
  { timeout: 20000 });
ok(await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   'once it commits, Save stays held: what is on screen was read before that, '
   + 'and staged work is at stake, so only Reload decides');
page.dialogs = [];
await page.click('#roadmapReread');
await page.waitForFunction(() => document.getElementById('roadmapBatch').hidden,
                           { timeout: 15000 });
ok(page.dialogs.some(d => /unsaved change/.test(d)),
   'reloading says what it would cost first');
ok(!await page.$eval('#roadmapSaveQuiet', b => b.disabled)
   || !(await open()).some(i => /typed while a session/.test(i.text)),
   '...and afterwards the list is the one on disk again');
// Waited for rather than read once: Reload is async and now re-reads every
// view, so "afterwards" is a state to arrive at and not an instant.
await page.waitForFunction(() => [...document.querySelectorAll('#roadmapList .txt')]
  .some(t => /not blocked at all/.test(t.textContent)), { timeout: 15000 });
ok(true, '...with the session\'s change on it');
await post({ action: 'remove', project: 'alpha',
             id: read().projects.alpha.find(r => /not blocked at all/.test(r.text)).id });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => ![...document.querySelectorAll('#roadmapList .txt')]
  .some(t => /not blocked at all/.test(t.textContent)), { timeout: 10000 });

// ---- the pane is the only scroller --------------------------------------
// The list used to be a scroll container with `overscroll-behavior: contain`,
// which was fine inside a modal that gave it a ceiling and wrong the moment
// the ceiling went: a container that cannot scroll and will not pass the
// gesture on. A finger landing anywhere on the list (most of the panel)
// did nothing, while the gaps between rows worked.
const scrollers = await page.evaluate(() => {
  const out = [];
  for (const el of document.querySelectorAll('.pane .nb, .pane .nb *')){
    // A textarea scrolling its own text is the point of a textarea.
    if (el.tagName === 'TEXTAREA') continue;
    // The reading room is not the panel: it is a modal over the whole screen,
    // it is the only thing on it, and a log too long for it has to scroll
    // somewhere. The rule this enforces is about the panel's own content,
    // where the pane underneath is the scroller.
    if (el.closest('.nbsheet')) continue;
    const s = getComputedStyle(el);
    if (/auto|scroll/.test(s.overflowY))
      out.push(`${el.id || el.className}:${s.overscrollBehaviorY}`);
  }
  return out;
});
ok(scrollers.length === 0,
   `nothing inside the notebook traps a scroll (${scrollers.join(', ') || 'none'})`);
ok(await page.evaluate(() => {
     const d = document.querySelector('.pane .nb').closest('.doc');
     return d && /auto|scroll/.test(getComputedStyle(d).overflowY); }),
   '...the pane\'s document is the one that scrolls');
ok(await page.evaluate(() => {
     const d = document.querySelector('.pane .nb').closest('.doc');
     return getComputedStyle(d).padding === '0px'; }),
   '...and it has no inset, so the notebook is the pane rather than a box in it');

// ---- one notebook per project, as many as there are projects -------------
// Each is its own clone with its own state, so a second project's opens
// beside the first rather than replacing it, and what is half-typed in one
// survives the other being looked at.
await page.evaluate(() => {
  notebooks.get('alpha').root.querySelector('[id="roadmapText"]').value = 'half-typed';
});
await page.evaluate(n => openNotebook(n), 'beta');
await page.waitForFunction(() => /beta/.test(
  document.querySelector('.pane .doc.on .nb h3')?.textContent || ''), { timeout: 15000 });
const nbTabs = await page.evaluate(() => tabs.filter(t => t.kind === 'notebook').map(t => t.arg));
ok(nbTabs.length === 2 && nbTabs.includes('alpha') && nbTabs.includes('beta'),
   `both projects' notebooks are open at once (${nbTabs})`);
ok(await page.evaluate(() => tabs.filter(t => t.kind === 'notebook')
     .every(t => tabLabel(t).includes(t.arg))),
   '...each named for its project');
await page.evaluate(n => openNotebook(n), 'alpha');
await page.waitForFunction(() => /alpha/.test(
  document.querySelector('.pane .doc.on .nb h3')?.textContent || ''), { timeout: 15000 });
ok(await page.evaluate(() =>
     notebooks.get('alpha').root.querySelector('[id="roadmapText"]').value) === 'half-typed',
   '...and coming back finds the field exactly as it was left');
await page.evaluate(() => {
  notebooks.get('alpha').root.querySelector('[id="roadmapText"]').value = '';
  hideTab(tabs.find(t => t.kind === 'notebook' && t.arg === 'beta').id);
});
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap').length > 0,
                           { timeout: 15000 });

// ---- where the tags sit ------------------------------------------------
ok(await page.$eval('#roadmapList .roadmap:has(.who) .body',
     el => el.firstElementChild.classList.contains('tags')),
   'a tag sits above the words, not beside them');

// ---- when something else has the keyboard ------------------------------
// A permission dialog swallows stray characters. Simulated with echo off,
// which has the same signature: the line does not appear, so Enter is not
// pressed and nothing is crossed out.
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', '-l', '--', 'stty -echo']);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', 'Enter']);
// Waited for on the pane's own tty rather than slept for (B345): under a
// whole run's load the shell had not run stty when the send began, the line
// echoed, and Enter followed. This check failed in five whole runs in a row
// and passed alone every time.
{
  const tty = execFileSync('tmux', ['display-message', '-p', '-t', 'claude-alpha', '#{pane_tty}'], { encoding: 'utf8' }).trim();
  let off = false;
  for (let i = 0; i < 100 && !off; i++){
    try { off = /(^|\s)-echo(\s|$)/.test(execFileSync('stty', ['-a', '-F', tty], { encoding: 'utf8' })); } catch { off = false; }
    if (!off) await new Promise(r => setTimeout(r, 100));
  }
  ok(off, 'the stand-in session has echo off, read from its tty, before the send');
}
// ...and the pane quiet: under a whole run's load a line sent earlier still
// had its shell's "command not found" on the way, which repeats the line, and
// it landed after the server's one-second settle and counted as this send's
// echo (B609). Two captures a second apart, the same, before the send.
{
  const cap = () => execFileSync('tmux', ['capture-pane', '-p', '-t', 'claude-alpha'], { encoding: 'utf8' });
  let prev = cap();
  for (let i = 0; i < 15; i++){
    await new Promise(r => setTimeout(r, 1000));
    const now = cap();
    if (now === prev) break;
    prev = now;
  }
}
const quiet = await post({ action: 'send', project: 'alpha', id: Number(mine.id) });
ok(quiet.status === 200 && quiet.body.typed && !quiet.body.sent,
   `a session that does not echo gets the line typed but not submitted (${quiet.status} ${JSON.stringify(quiet.body).slice(0, 120)})`);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', 'C-u']);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', '-l', '--', 'stty echo']);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', 'Enter']);

// ---- dropping ----------------------------------------------------------
await rowOpen(`#roadmapList .roadmap[data-id="${mine.id}"][data-step="-1"]`);
await page.click(`#roadmapList .roadmap[data-id="${mine.id}"][data-step="-1"] .rm`);
await page.waitForSelector('.dropbox', { timeout: 10000 });
ok(read().projects.alpha.some(r => String(r.id) === mine.id),
   'the bin asks first; it is one of the two ways anything leaves');
await page.click('.dropbox .danger');
await page.waitForFunction(id => !document.querySelector(`#roadmapList .roadmap[data-id="${id}"]`),
                           mine.id, { timeout: 10000 });
await saveList();
ok(!read().projects.alpha.some(r => String(r.id) === mine.id),
   '...and takes it off for good');
ok(/remove\s+R\d+\s+delete a project/.test(bbRoadmapEarly('history', '-n', '4')),
   '...into the log, with or without a reason typed into the box');

// ---- finishing one -------------------------------------------------------
// Only a session says a thing is done, through bb, because only a session
// knows. It comes off the list when it does: a list is read to find out what
// is left, and something finished is not left. The log is where it goes, and
// what tells "ticked off" apart from "dropped".
const fin = await post({ action: 'add', project: 'alpha', text: 'a job to finish' });
const finId = String(fin.body.item.id);
bbRoadmap('done', finId);
ok(!read().projects.alpha.some(r => String(r.id) === finId),
   'bb roadmap done takes the item off the list rather than fading it in place');
// ...and the Roadmap tab can still show it (R78): a Finished section under
// the list (R254 step 1), shut until opened, draws the ticked-off items with
// their plans, and the head counts them.
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => { const s = document.querySelector('.nb #roadmapDoneSect');
  return s && !s.hidden && /^\d+$/.test(document.querySelector('.nb #roadmapDoneN')?.textContent || ''); }, null, { timeout: 10000 });
ok(await page.$eval('.nb #roadmapDoneSect', e => !e.open) && !(await page.$('.nb #roadmapDoneList .grp')),
   'the finished items are a section shut until asked for');
ok(/\d+ finished/.test(await page.$eval('.nb #roadmapHint', h => h.textContent)), '...and the head counts them');
await page.click('.nb #roadmapDoneSect > summary');
await page.waitForSelector(`.nb #roadmapDoneList .grp.done[data-done="${finId}"]`, { timeout: 10000 });
ok(await page.$eval(`.nb #roadmapDoneList .grp.done[data-done="${finId}"] .txt`, e => e.textContent) === 'a job to finish',
   'Finished shows the ticked-off item, struck through, with no arrow');
ok(await page.evaluate(() => !!(document.querySelector('.nb #roadmapList').compareDocumentPosition(document.querySelector('.nb #roadmapDoneList')) & Node.DOCUMENT_POSITION_FOLLOWING)),
   '...below the live and shelved ones');
// A finished item is a fold like an open one, with Reopen where no release
// has shipped it (R254 step 2). Ticking off stays a session's (bb roadmap
// done), so the item goes back the way it came.
await page.click(`.nb #roadmapDoneList .grp.done[data-done="${finId}"] > summary`);
await page.waitForSelector(`.nb #roadmapDoneList .grp.done[data-done="${finId}"][open] [data-reopen]`, { state: 'visible', timeout: 5000 });
await page.click(`.nb #roadmapDoneList [data-reopen="${finId}"]`);
await page.waitForFunction(id => [...document.querySelectorAll('.nb #roadmapList > .grp')].some(g => g.dataset.id === id), finId, { timeout: 10000 });
ok(read().projects.alpha.some(r => String(r.id) === finId), 'Reopen on a finished item puts it back on the list, from the page');
// Its fold carries what it knows (R254 step 3): when it was added and by
// whom; and what shipped a thing is read off the CHANGELOG's dated
// releases, never typed (step 4).
await page.click(`.nb #roadmapList > .grp[data-id="${finId}"] > summary .dtog`);
await page.waitForSelector(`.nb #roadmapList > .grp[data-id="${finId}"] .dfacts:not([hidden])`, { timeout: 5000 });
ok(/Added.+, by you/.test(await page.$eval(`.nb #roadmapList > .grp[data-id="${finId}"] .dfacts`, e => e.textContent.replace(/\s+/g, ' '))),
   '...and its fold says when it was added and by whom');
ok(await page.evaluate(() => { const rel = [['0.7.0', 2000], ['0.6.0', 1000]];
  return shippedIn(500, rel) === '0.6.0' && shippedIn(1000, rel) === '0.6.0' && shippedIn(1500, rel) === '0.7.0'
    && shippedIn(2500, rel) === null && shippedIn(500, []) === ''; }),
   'what a thing shipped in is the first release dated after it, the next release for one done since');
// The changelog names items and bugs by id, and each becomes a link that
// opens its row: the view, its list narrowed to it.
ok(await page.evaluate(() => { const h = clLinks('fixed (B12, R3), not AB12 or B12x <b>');
  return /data-clref="B12"/.test(h) && /data-clref="R3"/.test(h) && !/data-clref="B12x"|data-clref="AB12"/.test(h) && /&lt;b&gt;/.test(h); }),
   'the changelog\'s ids are links, and only whole ids, its text escaped');
await page.evaluate(id => notebooks.get('alpha').find('R' + id), finId);
await page.waitForFunction(id => notebooks.get('alpha').where() === 'roadmap' && document.querySelector('.nb #roadmapFind').value === 'R' + id
  && [...document.querySelectorAll('.nb #roadmapList > .grp:not(.off)')].map(g => g.dataset.id).join() === id, finId, { timeout: 5000 });
ok(true, '...and following one opens the Roadmap narrowed to that item');
await page.fill('.nb #roadmapFind', '');
// Read first, as a session does: the reopen moved the list, and bb refuses
// a change made against an older read of it.
bbRoadmap();
const again = bbRoadmap('done', finId);
ok(/^done R/.test(again.trim()), `...and a session can tick it off again (${again.trim().slice(0, 60)})`);
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForSelector(`.nb #roadmapDoneList .grp.done[data-done="${finId}"]`, { timeout: 10000 });
// The search narrows the list and the Finished section alike, by words or
// by number, and the chips narrow the live list to its open or its shelved.
await page.fill('.nb #roadmapFind', 'a job to finish');
await page.waitForFunction(id => { const done = document.querySelector(`.nb #roadmapDoneList .grp.done[data-done="${id}"]`);
  return done && !done.classList.contains('off')
    && [...document.querySelectorAll('.nb #roadmapList > .grp')].every(g => g.classList.contains('off')); }, finId, { timeout: 5000 });
ok(true, 'searching narrows the list and the finished alike to what matches');
await page.fill('.nb #roadmapFind', '');
await page.click('.nb #roadmapDoneSect > summary');
await page.waitForFunction(() => !document.querySelector('.nb #roadmapDoneSect').open, null, { timeout: 5000 });
ok(!(await page.$('.nb #roadmapDoneList .grp')), '...and shutting the section folds them away again');
// A Save lit with nothing staged is a change the session has not been told
// about yet, and the bar says so rather than sitting there unexplained.
const untold = await post({ action: 'add', project: 'alpha', text: 'an untold change' });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => /not told to the session yet/.test(
  document.querySelector('.nb .sectbar[data-bar="roadmap"] .state')?.textContent || ''), null, { timeout: 10000 });
ok(await page.$eval('.nb .sectbar[data-bar="roadmap"] [data-ssave]', b => !b.disabled),
   'a change no session has heard of lights Save and says why on the bar');
await post({ action: 'remove', project: 'alpha', id: untold.body.item.id, why: 'only for the check' });
const afterDone = bbRoadmap('history');
ok(new RegExp(`done\\s+R${finId}\\s+a job to finish`).test(afterDone),
   '...and writes it into the history, under the word a session used');
ok(/\bdone\b/.test(afterDone) && /\bremove\b/.test(afterDone),
   '...which is what tells "ticked off" apart from "dropped": both leave, '
   + 'and only the log says which happened');
// ...and its number is never handed out again (bug B72): a number is the
// item's own, and "a gap means something was removed" only holds if nothing
// is numbered twice. It used to be max(on the list)+1, so ticking the
// newest items off gave their numbers to the next adds.
{
  const next = bbRoadmap('add', 'the number after a finished one');
  const nid = Number((next.match(/added R(\d+)/) || [])[1]);
  ok(nid > Number(finId),
     `a finished item's number is not reused: the next add is R${nid}, after R${finId}`);
  bbRoadmap('rm', String(nid), 'numbering fixture');
}
ok(!bbRoadmap('--prompt').includes('a job to finish'),
   '...so the next session is not handed work that is already finished');

// ---- what the server refuses -------------------------------------------
for (const [what, body] of [
  ['a project that does not exist', { action: 'add', project: 'nosuch', text: 'x' }],
  ['a project name that is really a path', { action: 'add', project: '../etc', text: 'x' }],
  ['an empty item', { action: 'add', project: 'alpha', text: '   ' }],
  ['an item nobody has', { action: 'edit', project: 'alpha', id: 9999, text: 'x' }],
  ['ticking one off over the wire: that is a session\'s word, not a button',
   { action: 'done', project: 'alpha', id: 1 }],
  ['an action nobody offers', { action: 'burn', project: 'alpha' }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
page.errors = [];

// What is kept and what a session is sent are two things (the operator, 29
// Sep): the list kept 30 with the parked ones counted, to keep the prompt
// short, and a project with 17 open and 13 parked could not record a 31st.
// The prompt keeps to a share now (preamble.mjs), and the list's own limit
// is on the open ones.
const many = read();
many.projects.gamma = Array.from({ length: 30 }, (_, i) =>
  ({ id: i + 1, text: `item ${i + 1}`, done: false, added: 1, by: 'you' }))
  .concat(Array.from({ length: 40 }, (_, i) =>
    ({ id: 500 + i, text: `parked ${i + 1}`, done: false, added: 1, by: 'you', shelved: 1790000000 })));
writeFileSync(FILE, JSON.stringify(many));
const more = await post({ action: 'add', project: 'gamma', text: 'a thirty-first, beside forty parked' });
ok(more.status === 200 && !more.body.error,
   'a list of thirty open and forty parked takes another: the parked are not counted and thirty is not the limit');
// The cap is a guard against a runaway, not a working limit (the operator,
// 15 Oct): five thousand open.
many.projects.gamma = Array.from({ length: 5000 }, (_, i) =>
  ({ id: i + 1, text: `item ${i + 1}`, done: false, added: 1, by: 'you' }));
writeFileSync(FILE, JSON.stringify(many));
const over = await post({ action: 'add', project: 'gamma', text: 'one too many' });
ok(over.status === 400 && /5000 open items is the limit: finish, park or drop some first/.test(over.body.error),
   `...and five thousand open is where it says what to do instead (${over.body.error})`);
page.errors = [];

// ---- building a plan in the panel --------------------------------------
// A plain item becomes a plan by being given a step; the field stays open, so
// three steps is three lines of typing rather than three dialogs.
const plainId = (await open()).find(i => i.step === '-1'
  && i.text.startsWith('make the picker')).id;
await page.click(`#roadmapList .addstep[data-id="${plainId}"] button`);
await page.fill(`#roadmapList .addstep[data-id="${plainId}"] textarea`, 'first, widen it');
await page.keyboard.press('Enter');
await page.waitForFunction(id => document.querySelectorAll(
  `#roadmapList .grp:has(.roadmap[data-id="${id}"]) .roadmap.step`).length === 1, plainId,
  { timeout: 10000 });
ok(await page.$eval(`#roadmapList .addstep[data-id="${plainId}"] textarea`, e => !!e),
   'the step field stays open, so a plan is typed rather than assembled');
await page.fill(`#roadmapList .addstep[data-id="${plainId}"] textarea`, 'then re-measure');
await page.keyboard.press('Enter');
await page.waitForFunction(id => document.querySelectorAll(
  `#roadmapList .grp:has(.roadmap[data-id="${id}"]) .roadmap.step`).length === 2, plainId,
  { timeout: 10000 });
// Two steps typed, neither written: this is the case the staging is for.
// Look at the pair, then keep them or drop them as one.
ok(!(read().projects.alpha.find(r => String(r.id) === plainId).steps || []).length,
   '...and neither of them is on disk while the field is still open');
await page.keyboard.press('Escape');
await saveList();
let made = read().projects.alpha.find(r => String(r.id) === plainId);
ok(made.steps.length === 2 && made.steps[0].text === 'first, widen it'
   && made.steps[1].text === 'then re-measure',
   'Save writes them, in the order they were typed');

// A step's own words are editable, which they were not: the pencil is on
// every row, and a plan is written before it is right. In a box under the row
// rather than a prompt(), because a step can be several lines and a prompt is
// one by construction, and it would have flattened them on the way back.
await rowOpen(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"]`);
await page.click(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"] .ed`);
await page.waitForSelector('.editbox textarea', { timeout: 10000 });
ok(await page.$eval('.editbox textarea', t => t.value) === 'first, widen it',
   'the pencil opens the line as it stands, ready to change');
await page.fill('.editbox textarea', 'first, widen it a lot');
await page.click('.editbox .primary');
await page.waitForFunction(() => !document.querySelector('.editbox'), { timeout: patience(10000) })
  .catch(() => { throw new Error('the reword box is still open after Save was pressed: its handler did not run (B311)'); });
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="0"] .txt`)?.textContent
  === 'first, widen it a lot', plainId, { timeout: patience(20000) });
await saveList();
ok(read().projects.alpha.find(r => String(r.id) === plainId).steps[0].text
   === 'first, widen it a lot',
   'the pencil rewords a step, not only an item');

// One step, several lines. A step is a message the operator sends by hand, so
// the expensive unit is the step and the cheap one is the line inside it,
// which only works if a step can hold more than a sentence.
await rowOpen(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"]`);
await page.click(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"] .ed`);
await page.waitForSelector('.editbox textarea', { timeout: 10000 });
await page.fill('.editbox textarea', 'widen the select\n\nand check it at 412px');
await page.click('.editbox .primary');
await page.waitForFunction(() => !document.querySelector('.editbox'), { timeout: patience(10000) })
  .catch(() => { throw new Error('the reword box is still open after Save was pressed: its handler did not run (B311)'); });
await page.waitForFunction(id => /\n/.test(document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="0"] .txt`)?.textContent || ''),
  plainId, { timeout: 10000 });
await saveList();
ok(read().projects.alpha.find(r => String(r.id) === plainId).steps[0].text
   === 'widen the select\n\nand check it at 412px',
   'a step keeps the breaks it was written with');
ok(await page.$eval(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"] .txt`,
     el => getComputedStyle(el).whiteSpace.startsWith('pre')),
   '...and the panel shows them rather than running the lines together');

// ...and a box open in the list is not taken apart by somebody else's write.
// The reword box, the drop box, the send note and the + step field are DOM
// put under a row after the render, so a redraw takes them and every word
// typed into them. The poll's guard upstream watches for STAGED changes, and
// typing is not staged until Save, so a session running `bb roadmap add` in
// the background deleted a half-written rewording under the finger holding
// it. Bugs has skipped its redraw while a form is open since it was built.
{
  await rowOpen(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"]`);
  await page.click(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"] .ed`);
  await page.waitForSelector('.editbox textarea', { timeout: 10000 });
  await page.fill('.editbox textarea', 'half a thought, still typing');
  // Somebody else writes the same project, as a session does: another
  // process entirely, through bb, which is the case the file lock exists for.
  bbRoadmap('add', 'from somebody else');
  // The re-read the revisions poll makes, driven rather than waited on: the
  // poll's own timer is 30s while the page is hidden, which headless is, so
  // waiting on a clock here would pass whatever the code did. The live
  // notebook, off the map: getNotebook() MAKES one when the key misses, and a
  // fresh notebook answers every question with "nothing is open here".
  const tick = async () => {
    await page.evaluate(() => getNotebook('alpha').reload());
    await new Promise(r => setTimeout(r, 300));
  };
  await tick(); await tick();
  ok(await page.$eval('.editbox textarea', t => t.value) === 'half a thought, still typing',
     'a redraw from elsewhere leaves a half-typed rewording alone, box and words');
  // And the arrival is not lost: the panel has not recorded the revision it
  // skipped, so the next poll after the box shuts draws what came in.
  await page.click('.editbox .stop');
  await page.waitForFunction(() => !document.querySelector('.editbox'), { timeout: 10000 });
  let landed = false;
  for (let i = 0; i < 20 && !landed; i++){
    await tick();
    landed = await page.evaluate(() => /from somebody else/.test(
      document.getElementById('roadmapList')?.textContent || ''));
  }
  ok(landed, '...and what arrived while it was open is drawn once the box is shut');
}
await rowOpen(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"]`);
await page.click(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"] .ed`);
await page.waitForSelector('.editbox textarea', { timeout: 10000 });
await page.fill('.editbox textarea', 'first, widen it a lot');
await page.click('.editbox .primary');
await page.waitForFunction(() => !document.querySelector('.editbox'), { timeout: patience(10000) })
  .catch(() => { throw new Error('the reword box is still open after Save was pressed: its handler did not run (B311)'); });
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="0"] .txt`)?.textContent
  === 'first, widen it a lot', plainId, { timeout: patience(20000) });

// ...and the step field has a way out that is not the Escape key a phone
// keyboard does not have.
await page.click(`#roadmapList .addstep[data-id="${plainId}"] button`);
await page.waitForSelector(`#roadmapList .addstep[data-id="${plainId}"] textarea`);
await page.click(`#roadmapList .addstep[data-id="${plainId}"] .stop`);
await page.waitForFunction(id => !document.querySelector(
  `#roadmapList .addstep[data-id="${id}"] textarea`), plainId, { timeout: 10000 });
ok(true, 'Cancel closes the step field without adding anything');

// ---- the details under a line --------------------------------------------
// The row's words are the decision; the details are the workings (which
// files, which functions, the approach), earmarked when the plan is written
// so the session that works it does not start from a cold grep.
bbRoadmapEarly('info', plainId, 'lives in scripts/dashboard/roadmap.py\n\nGUI half: stepRow');
ok(read().projects.alpha.find(r => String(r.id) === plainId).info
     === 'lives in scripts/dashboard/roadmap.py\n\nGUI half: stepRow',
   'bb roadmap info attaches details to an item, breaks kept');
bbRoadmapEarly('info', plainId, '1', 'the select is built in stepRow()');
ok(read().projects.alpha.find(r => String(r.id) === plainId).steps[0].info
     === 'the select is built in stepRow()',
   '...and to one step of it, numbered the way a human reads it');
// The details are the long half and only the session that picks the item up
// needs them, so the prompt carries a pointer and `bb roadmap show` carries
// the text. On this repository that was 35KB of a 45KB block that every
// conversation paid for whether or not it touched the roadmap.
{
  const block = bbRoadmapEarly('--prompt');
  ok(!/lives in scripts\/dashboard\/roadmap\.py/.test(block) && /`bb roadmap show R4` prints one whole/.test(block),
     'the prompt names where the details are rather than carrying them');
  ok(/lives in scripts\/dashboard\/roadmap\.py/.test(bbRoadmapEarly('show', plainId)),
     '...and that command prints them in full');
}

await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(id => !!document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="-1"] .dtog`), plainId,
  { timeout: 10000 });
ok(await page.$eval(`#roadmapList .roadmap[data-id="${plainId}"][data-step="-1"] .dinfo`,
     el => el.hidden),
   'the panel shows a details fold, closed: the words are the decision, this is the workings');
// Watched across the click rather than read after it: under a whole run's
// load the 180 ms tween could finish before a read after the click, and the
// check failed in a four-worker run and passed alone (B390).
const slid = await animatedDuring(page, () =>
  page.click(`#roadmapList .roadmap[data-id="${plainId}"][data-step="-1"] .dtog`));
ok(await page.$eval(`#roadmapList .roadmap[data-id="${plainId}"][data-step="-1"] .dinfo`,
     el => !el.hidden && /GUI half: stepRow/.test(el.textContent)),
   '...and one tap opens it, breaks and all');
// It slides rather than appearing: the same height tween the sidebar cards
// fold with, so the rows below ride down instead of jumping.
ok(slid.length > 0, `...as a slide, not a snap (${slid.join(' ') || 'nothing animated'})`);
await page.waitForFunction(id => !document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="-1"] .dinfo`).getAnimations().length,
  plainId, { timeout: 5000 });
ok(await page.$eval(`#roadmapList .roadmap[data-id="${plainId}"][data-step="-1"] .dinfo`,
     el => el.offsetHeight > 0 && !el.style.height),
   '...and settles at its real height, with the inline one taken back off');

// Editing them is part of the reword box, staged like everything else there.
await rowOpen(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"]`);
await page.click(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"] .ed`);
await page.waitForSelector('.editbox .dta', { timeout: 10000 });
ok(await page.$eval('.editbox .dta', t => t.value) === 'the select is built in stepRow()',
   'the reword box opens with the details as they stand');
await page.fill('.editbox .dta', 'stepRow(), and the CSS at .roadmap .dinfo');
await page.click('.editbox .primary');
await page.waitForFunction(() => !document.querySelector('.editbox'), { timeout: patience(10000) })
  .catch(() => { throw new Error('the reword box is still open after Save was pressed: its handler did not run (B311)'); });
await page.waitForFunction(id => /CSS at/.test(document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="0"] .dinfo`)?.textContent || ''),
  plainId, { timeout: 10000 });
ok(read().projects.alpha.find(r => String(r.id) === plainId).steps[0].info
     === 'the select is built in stepRow()',
   '...staged, not written; the file still has the old details');
await saveList();
ok(read().projects.alpha.find(r => String(r.id) === plainId).steps[0].info
     === 'stepRow(), and the CSS at .roadmap .dinfo',
   '...until Save, like every other change the panel makes');

// A sent step carries its details, since they are the half the work needs.
await post({ action: 'send', project: 'alpha', id: Number(plainId), step: 0 });
ok(/Details: stepRow\(\), and the CSS/.test(tmuxCapture('claude-alpha')),
   'sending a step sends its details with it');
await post({ action: 'cross', project: 'alpha', id: Number(plainId), step: 0, on: false });
bbRoadmapEarly('info', plainId, '');
bbRoadmapEarly('step', 'info', plainId, '1', '');
await page.evaluate(() => notebooks.get('alpha').reload());
// The caret stays (it opens the row's actions, R223); the details go, and
// the caret reads more rather than details.
await page.waitForFunction(id => !document.querySelector(`#roadmapList .roadmap[data-id="${id}"] .dinfo`)
  && [...document.querySelectorAll(`#roadmapList .roadmap[data-id="${id}"] .dtog`)].every(b => /more/.test(b.textContent)),
  plainId, { timeout: 10000 });
ok(true, 'clearing the details takes them off the row, the caret reading more');

// ---- nothing lands until Save, and Close is the other answer ------------
// Deletions and rewords are staged like everything else: the panel is a form,
// and a form you can close is a form you can change your mind in.
await saveList();
const untouched = JSON.stringify(read().projects.alpha);
const wasText = read().projects.alpha.find(r => String(r.id) === plainId).text;
await rowOpen(`#roadmapList .roadmap[data-id="${plainId}"][data-step="-1"]`);
await page.click(`#roadmapList .roadmap[data-id="${plainId}"][data-step="-1"] .ed`);
await page.waitForSelector('.editbox textarea', { timeout: 10000 });
await page.fill('.editbox textarea', 'a wording nobody asked for');
await page.click('.editbox .primary');
await page.waitForFunction(() => !document.querySelector('.editbox'), { timeout: patience(10000) })
  .catch(() => { throw new Error('the reword box is still open after Save was pressed: its handler did not run (B311)'); });
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="-1"] .txt`)?.textContent
  === 'a wording nobody asked for', plainId, { timeout: patience(20000) });   // late under load (B311)
await rowOpen(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"]`);
await page.click(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"] .rm`);
await page.waitForSelector('.dropbox .danger', { timeout: 10000 });
await page.click('.dropbox .danger');
await page.waitForFunction(id => document.querySelectorAll(
  `#roadmapList .grp:has(.roadmap[data-id="${id}"]) .roadmap.step`).length === 1,
  plainId, { timeout: 10000 });
ok(JSON.stringify(read().projects.alpha) === untouched,
   'a reword and a deletion both wait for Save, the same as an addition');

// Revert is where Close used to be, and it is the only thing left for a
// button beside Save to mean now that saving does not close anything.
ok(!await page.$eval('#roadmapRevert', b => b.disabled),
   'unsaved changes arm Revert as well as Save');
page.dialogs = [];
await page.click('#roadmapRevert');
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="-1"] .txt`)?.textContent !== 'a wording nobody asked for',
  plainId, { timeout: 10000 });
ok(page.dialogs.some(d => /Revert 2 changes to the list/.test(d)),
   'Revert names what it would throw away, rather than asking in the abstract');
ok(JSON.stringify(read().projects.alpha) === untouched,
   '...and it never reached the file in the first place');
ok(await page.$eval('#roadmapRevert', b => b.disabled),
   '...and it goes dead once there is nothing left to throw away');
const reopened = await open();
ok(reopened.filter(i => i.id === plainId && i.step !== '-1').length === 2
   && reopened.find(i => i.id === plainId && i.step === '-1').text === wasText,
   '...and both the deleted step and the original wording are back on screen');

// ---- moving things about -----------------------------------------------
// Its own mode: five controls and a number do not fit a phone row, and
// nobody rearranges a list at the same moment they are sending from it.
await page.$eval('#roadmapOrder', b => b.scrollIntoView({block: 'center'}));
await page.click('#roadmapOrder');
// The arrows are what arms a send, and the box only exists under an armed
// one, so in this mode there is nothing to send with and nothing to send.
await page.waitForFunction(() => !document.querySelector('#roadmapList .roadmap .go'),
                           null, { timeout: 15000 });
ok(await page.$('.sendbox') === null
   && await page.$$eval('#roadmapList .roadmap .go', g => g.length === 0)
   && await page.$$eval('#roadmapList .roadmap .mv', m => m.length > 0),
   'reordering swaps the row controls rather than crowding in beside them');
ok(await page.$$eval('#roadmapList .addstep', a => a.length === 0),
   '...and puts the step field away: the question here is only where things sit');

const order = () => page.$$eval('#roadmapList .grp .roadmap[data-step="-1"] .txt',
  ts => ts.map(t => t.textContent.slice(0, 14)));
const was = await order();
// The first one, moved down, whichever it is. `plainId` may already be last,
// and "move the last one down" is correctly a refusal.
const firstId = await page.$eval('#roadmapList .grp .roadmap[data-step="-1"]',
                                 t => t.dataset.id);
await page.click(`#roadmapList .roadmap[data-id="${firstId}"][data-step="-1"] .mv[data-dir="1"]`);
await page.waitForFunction(o => JSON.stringify([...document.querySelectorAll(
  '#roadmapList .grp .roadmap[data-step="-1"] .txt')].map(t => t.textContent.slice(0, 14)))
  !== JSON.stringify(o), was, { timeout: 10000 });
const now = await order();
ok(now.indexOf(was[0]) === 1 && now.indexOf(was[1]) === 0,
   'an item moves down past the one below it');
ok(JSON.stringify(read().projects.alpha.map(r => r.text.slice(0, 14))) === JSON.stringify(was),
   '...on screen only; the file still has the order it started with');
ok(!await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   '...and both Saves are armed, because there is something to commit');

// Leaving the mode is a mode switch and nothing more: the shuffle is staged
// like every other change now, so it survives until Save or Close decides.
page.dialogs = [];
await page.click('#roadmapOrder');
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap .mv').length === 0,
                           { timeout: 10000 });
ok(page.dialogs.length === 0,
   'leaving the mode asks nothing; the shuffle is held, not thrown away');
ok(JSON.stringify(await order()) !== JSON.stringify(was),
   '...and the order on screen is still the rearranged one');
ok(!await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   '...with Save still holding it');

await saveList();
const kept = await order();
ok(JSON.stringify(read().projects.alpha.map(r => r.text.slice(0, 14))) === JSON.stringify(kept)
   && JSON.stringify(kept) !== JSON.stringify(was),
   'Save is what writes it, and the file is then the order on screen');
// A step that has gone does not move, and nothing moves above it.
await post({ action: 'cross', project: 'alpha', id: Number(plainId), step: 0, on: true });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="0"]`)?.classList.contains('sent'),
  plainId, { timeout: 10000 });
await page.click('#roadmapOrder');
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap .mv').length > 0);
ok(await page.$eval(`#roadmapList .roadmap[data-id="${plainId}"][data-step="0"] .mv`,
     b => b.disabled),
   'a crossed step is pinned: the past of a plan does not shuffle');
const up1 = await post({ action: 'move', project: 'alpha', id: Number(plainId),
                         step: 1, dir: -1 });
ok(up1.status === 400 && /has gone/.test(up1.body.error),
   '...and nothing moves above it either, which is what keeps the crossed ones a block');
page.errors = [];

// A crossed *item* is not a crossed step: nothing behind it depends on where
// it sits, so it moves like any other line. Only a group's steps are pinned,
// because every rule about what can be sent reads them as a block.
// A fresh one, because everything else on this list is a group by now.
const lone = await post({ action: 'add', project: 'alpha', text: 'a line on its own' });
const loneId = String(lone.body.item.id);
await post({ action: 'cross', project: 'alpha', id: Number(loneId), on: true });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="-1"]`)?.classList.contains('sent'),
  loneId, { timeout: 10000 });
ok(await page.$$eval(`#roadmapList .roadmap[data-id="${loneId}"][data-step="-1"] .mv`,
     bs => bs.every(b => !b.disabled)),
   'a crossed single item still moves; the pin is a rule about groups');
// Up, because a new item goes in at the bottom and "move the last one down"
// is correctly a refusal.
const moved = await post({ action: 'move', project: 'alpha', id: Number(loneId),
                           dir: -1 });
ok(moved.status === 200, '...and the server agrees');
const after = read().projects.alpha;
ok(after[after.length - 2].text === 'a line on its own',
   '...and it really moved, crossed or not');
await post({ action: 'remove', project: 'alpha', id: Number(loneId) });
page.errors = [];

await post({ action: 'cross', project: 'alpha', id: Number(plainId), step: 0, on: false });
await page.click('#roadmapOrder');
await page.waitForFunction(() => !!document.querySelector('#roadmapList .roadmap .go'));
ok(true, 'and the send arrows come back');
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap').length > 0);

// ---- the row's button lights while the tab is open -----------------------
await page.evaluate(() => refresh());
await page.waitForFunction(() => tabOf(panes[0])?.kind === 'notebook', null, { timeout: 15000 });
ok(true, "the notebook is the page on show while it is open");

// ---- a document has a reading width --------------------------------------
// An ultrawide pane put a row's name at one end of two thousand pixels and
// the bin that acts on it at the other.
const ultra = await newPage(browser, { viewport: { width: 2200, height: 900 } });
await ultra.goto(URL);
await ready(ultra);
await ultra.evaluate(n => openNotebook(n), 'alpha');
await nbShown(ultra);
await ultra.waitForFunction(
  // Loaded, whatever it holds, not merely started. This used to match the
  // "loading…" placeholder, so it was satisfied the instant the panel opened
  // and said nothing about the list arriving; that only came to light when
  // the placeholder stopped sharing a class with the empty state.
  () => { const l = document.querySelector('#roadmapList');
          return !!l && !l.querySelector('.loading'); },
                           { timeout: 20000 });
const spread = await ultra.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  const pane = nb.closest('.doc').getBoundingClientRect();
  return { nb: Math.round(nb.getBoundingClientRect().width),
           pane: Math.round(pane.width) };
});
ok(spread.pane > 1500 && spread.nb <= 1100,
   `the notebook keeps a reading width in a ${spread.pane}px pane (${spread.nb}px)`);
await ultra.evaluate(() => openToolchains());
await ultra.waitForSelector('.doc .tc', { timeout: 20000 });
ok(await ultra.evaluate(() => {
     const p = document.querySelector('.doc.on .tc');
     return p && p.getBoundingClientRect().width <= 1100; }),
   '...and so does the Toolchains tab, where the bin was furthest from its row');
await closePage(ultra);
// The two pages are one account, and an account's tabs are one layout: the
// Toolchains tab the wide page opened could become the active tab here too,
// and under a whole run's load that landed before the Save below was
// pressed, with the notebook's footer behind it (B396). The notebook first.
// Opening it straight away was not enough (B414): this page adopts the
// wide page's layout on its next status poll, which could come after the
// notebook was shown, even in the suite run alone. So first this page holds
// the layout revision the server has, and only then is the notebook shown.
const serverRev = await page.evaluate(async () => (await (await fetch('/api/status')).json()).layout?.rev ?? -1);
await page.waitForFunction(r => myRev >= r, serverRev, { timeout: 20000 });
await page.evaluate(() => openNotebook('alpha', 'roadmap'));
await nbShown(page);

// ---- one Save, and what it does NOT do ----------------------------------
// There were two, and the second typed the change into a running session's
// input box, the only way anything reached a session before the prompt hook
// got a free channel back (roadmap #27). Now the session is told by itself,
// so the panel writes and says nothing, and this asserts the silence.
await post({ action: 'add', project: 'alpha', text: 'something to settle' });
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => { const b = document.getElementById('roadmapSaveQuiet');
  return !b.disabled && b.offsetParent; });
ok(await page.$('#roadmapSave') === null,
   'there is one Save in the footer, not two');
const beforeQuiet = tmuxCapture('claude-alpha').length;
await page.click('#roadmapSaveQuiet');
await page.waitForFunction(() => {
  const b = document.getElementById('roadmapSaveQuiet');
  return b.getAttribute('aria-busy') !== 'true' && b.disabled;
}, { timeout: 15000 });
ok(tmuxCapture('claude-alpha').length === beforeQuiet,
   'Save spends no line of the session\'s conversation; it is told on its own '
   + 'next prompt instead');
ok((read().unsaved?.alpha || {}).roadmap === false,
   '...and it really is settled, so it stops asking');
// The channel that DOES still carry the line: a step being sent is a message
// going to that session anyway, so what moved in the notebook rides along on
// it rather than costing a second one.
const plainToSend = read().projects.alpha.find(r => !(r.steps || []).length
                                                    && !r.shelved && !r.sent);
await post({ action: 'add', project: 'alpha', text: 'and something to tell' });
await page.evaluate(() => notebooks.get('alpha').reload());
await post({ action: 'send', project: 'alpha', id: plainToSend.id, step: null,
             tell: true });
const told = tmuxCapture('claude-alpha');
ok(/shared to-do list for this project/.test(told),
   'a sent step carries what moved in the notebook, naming the to-do list');
ok(!/notes about how you work/.test(told.slice(beforeQuiet)),
   '...and not the memories, which did not move');

// ---- nothing slides sideways -------------------------------------------
// Four buttons in the footer did not fit a phone, and a footer that does not
// fit makes the box scroll horizontally, so the whole panel slid under the
// thumb every time it was touched.
// ---- a session starting under an open notebook --------------------------
// Whether a step can be sent is a fact about the session running beside it,
// and it used to arrive only with the list, fetched when the notebook opened
// and then never again. So starting Claude while looking at the Roadmap left
// every arrow gray until the tab was closed and reopened.
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => document.querySelectorAll('#roadmapList .roadmap').length > 0);
ok((await open()).some(i => i.can), 'with the session up, something can be sent');
tmuxKill('claude-alpha');
await page.evaluate(() => refresh());
await page.waitForFunction(() => [...document.querySelectorAll('#roadmapList .roadmap .go')]
  .every(g => g.getAttribute('aria-disabled') === 'true'), null, { timeout: 15000 });
ok(/no session running/.test(await page.$eval('#roadmapHint', h => h.textContent)),
   'the session going away puts the arrows down, without touching the tab');
// ...and a dead arrow says why when pressed (B213). It used to be a disabled
// button, which swallows the press: the reason lived in a hover title a
// finger never sees and in the line under the whole list.
// Through the DOM: Playwright itself refuses to click what is aria-disabled.
await page.$eval('#roadmapList .roadmap .go', b => b.click());
ok(/no Claude session is running here/.test(await page.$eval('#toast', t => t.textContent)),
   `pressing a dead arrow says why in the band (${await page.$eval('#toast', t => t.textContent.slice(0, 60))})`);
tmuxNew('claude-alpha');
await page.evaluate(() => refresh());
await page.waitForFunction(() => [...document.querySelectorAll('#roadmapList .roadmap .go')]
  .some(g => g.getAttribute('aria-disabled') !== 'true'), null, { timeout: 15000 });
ok(/claude-alpha running/.test(
     await page.$eval('#roadmapHint', h => h.textContent)),
   '...and starting one brings them back, with the notebook left open the whole time');

const phone = await newPage(browser, { viewport: { width: 400, height: 860 },
                                       isMobile: true, hasTouch: true });
await phone.goto(URL);
await ready(phone);
await phone.evaluate(n => openNotebook(n), 'alpha');
await nbShown(phone);
await nbTab(phone, 'roadmap');
await phone.waitForSelector('#roadmapList .roadmap', { timeout: 20000 });
// The head reads the same way the other three tabs do: the view's own summary
// and its History first, then the row of things that change the list.
ok(await phone.evaluate(() => {
     const head = document.querySelector('[data-view="roadmap"] .nbhead');
     const add = document.getElementById('roadmapAddBar');
     return !!head && !!add && add.classList.contains('addbar')
       && head.contains(document.getElementById('roadmapHint'))
       && head.contains(document.getElementById('roadmapLog'))
       && /^Add to roadmap$/.test(document.getElementById('roadmapShow').textContent.trim())
       && add.contains(document.getElementById('roadmapOrder'))
       && document.getElementById('roadmapForm').hidden
       && head.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING;
   }),
   'the summary and History sit above the add band: Add to roadmap and Reorder, the box rolled up until asked for (R119 step 4)');
// The strip does not spill off a phone. Five labels are wider than 360px and
// flex items will not shrink below their text, so it scrolls sideways
// instead, and the tab that is current has to be inside the visible part of it.
const strip = await phone.evaluate(() => {
  const el = document.querySelector('.pane .nb .nbtabs');
  const on = el.querySelector('button.on');
  const e = el.getBoundingClientRect(), b = on.getBoundingClientRect();
  return { spills: el.scrollWidth > el.clientWidth,
           clipped: el.clientWidth >= el.scrollWidth
                    || getComputedStyle(el).overflowX === 'auto',
           onScreen: b.left >= e.left - 1 && b.right <= e.right + 1 };
});
ok(strip.clipped && strip.onScreen,
   'the notebook strip scrolls rather than spilling, with the current tab in view');

await phone.click('.pane .nb .nbtabs [data-v="briefing"]'); // every control on screen at once
await phone.evaluate(() => { document.getElementById('memSect').open = true; });
await phone.waitForFunction(() => document.getElementById('memList').checkVisibility());
const wide = await phone.evaluate(() => {
  const out = [];
  for (const sel of ['.modal .box', '#roadmapList', '#memList', '.modal .foot',
                     '.roadmapadd', '.sendbox'])
    for (const el of document.querySelectorAll(sel))
      if (el.scrollWidth > el.clientWidth + 1)
        out.push(sel + ' ' + el.scrollWidth + '>' + el.clientWidth);
  return out;
});
ok(wide.length === 0, `nothing in the panel scrolls sideways on a phone (${wide.join(', ')})`);
ok(await phone.evaluate(() =>
     document.documentElement.scrollWidth <= document.documentElement.clientWidth),
   '...and neither does the page behind it');
await closePage(phone);

// ---- two writers, which is what the notebook actually has ----------------
// The dashboard is one process and `bb roadmap` is another, and both do
// load-mutate-save. The lock around that was a threading.Lock, which guards
// the threads of ONE process, so the second write landed on top of the first
// and the item added from a terminal was simply not there afterwards.
const race = execFileSync('python3', ['-c', `
import json, os, subprocess, sys, tempfile
sf = ${JSON.stringify(new globalThis.URL('../statefile.py', import.meta.url).pathname)}
d = tempfile.mkdtemp(); f = os.path.join(d, 'x.json')
json.dump({'n': 0}, open(f, 'w'))
prog = """
import importlib.util, json, os, sys, time
spec = importlib.util.spec_from_file_location('sf', sys.argv[1])
sf = importlib.util.module_from_spec(spec); spec.loader.exec_module(sf)
for _ in range(25):
    with sf.locked(sys.argv[2]):
        n = json.load(open(sys.argv[2]))['n']
        time.sleep(0.001)                 # the window a lost update lives in
        sf.write_json(sys.argv[2], {'n': n + 1})
"""
ps = [subprocess.Popen([sys.executable, '-c', prog, sf, f]) for _ in range(4)]
[p.wait() for p in ps]
print(json.dumps({'got': json.load(open(f))['n'], 'want': 100}))
`], { encoding: 'utf8' });
const RACE = JSON.parse(race.trim().split('\n').pop());
ok(RACE.got === RACE.want,
   'four processes making the same change keep every one of them: the lock is on '
   + 'the file, so the other writer waits rather than overwriting');

// Re-entrant, because flock is per open file description: a second acquire in
// the same process blocks against the first, and a mutator reaching another
// through the front door would deadlock on itself.
const reent = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys, tempfile
spec = importlib.util.spec_from_file_location('sf', ${
  JSON.stringify(new globalThis.URL('../statefile.py', import.meta.url).pathname)})
sf = importlib.util.module_from_spec(spec); spec.loader.exec_module(sf)
f = os.path.join(tempfile.mkdtemp(), 'x.json')
with sf.locked(f):
    with sf.locked(f):
        pass
h = sf.on(lambda: f)
with h: pass
with h: pass                              # a handle is reusable, unlike a cm
print(json.dumps({'ok': True}))
`], { encoding: 'utf8' });
ok(JSON.parse(reent.trim().split('\n').pop()).ok,
   '...and re-entrant, so a mutator that reaches another does not deadlock on itself');

// ---- a step a session finished ------------------------------------------
// Sent is the dashboard's mark and says a line went. A session told in chat
// to go ahead had no mark of its own, so it reworded the step to say LANDED
// and the panel went on offering it. `bb roadmap step done` is that mark:
// struck like sent, ticked rather than numbered, skipped by the frontier,
// and cleared by a re-send, which is the operator saying it was not done.
bbRoadmapEarly('add', 'ship the widget', '--step', 'cut the hole', '--step', 'fit the widget',
            '--step', 'paint it');
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => [...document.querySelectorAll('#roadmapList .roadmap .txt')]
  .some(t => t.textContent === 'fit the widget'));
let widget = (await open()).find(i => i.text === 'ship the widget');
ok(/step 2 of R\d+ done/.test(bbRoadmapEarly('step', 'done', widget.id, '2', 'told in chat')),
   'a session marks one step of a plan done, out of send order');
// ---- the letter (roadmap #28): R on every item, the bug tracker's B refused ----
ok(new RegExp(`R${widget.id}  ship the widget`).test(bbRoadmapEarly('show', `r${widget.id}`)),
   'a lower-case r on the number names the same item');
ok(/B\d+ is a bug; a roadmap item is R\d+/.test((() => {
     try { return bbRoadmapEarly('done', `B${widget.id}`); } catch (e) { return e.stderr.toString(); } })()),
   '...and the bug tracker\'s letter is refused, naming both tabs');
ok(new RegExp(`R${widget.id}`).test(bbRoadmapEarly()) && !/ship the widget/.test(bbRoadmapEarly('--prompt')),
   'the list names an item with its letter, and the prompt block carries no item');
ok(await page.$eval(`#roadmapList .roadmap[data-id="${widget.id}"] .n.id`,
                    (el, id) => el.textContent === 'R' + id, widget.id),
   '...and so does the row in the notebook');
ok(/already done/.test((() => { try { return bbRoadmapEarly('step', 'done', widget.id, '2'); }
                               catch (e) { return String(e.stderr); } })()),
   '...and cannot mark it twice');
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="1"]`)?.classList.contains('done'), widget.id);
const drawn = await page.$$eval(`#roadmapList .roadmap[data-id="${widget.id}"]`, ts => ts.map(t => ({
  step: t.dataset.step, done: t.classList.contains('done'), sent: t.classList.contains('sent'),
  n: t.querySelector('.n')?.textContent, can: t.querySelector('.go').getAttribute('aria-disabled') !== 'true',
  why: saidOf(t.querySelector('.go')) })));
ok(drawn.find(d => d.step === '1').done && !drawn.find(d => d.step === '1').sent
   && drawn.find(d => d.step === '1').n === '✓',
   'the panel draws it struck with a tick where its number was, and not as sent');
ok(drawn.find(d => d.step === '0').can && !drawn.find(d => d.step === '2').can
   && /step 1 comes first/.test(drawn.find(d => d.step === '2').why),
   '...the frontier is still step 1, and step 3 waits on it, not on the done one');
ok(drawn.find(d => d.step === '1').can && /finished this/.test(drawn.find(d => d.step === '1').why),
   '...and the done step stays sendable, worded as the override it would be');
ok(/2\. fit the widget  \(done\)/.test(bbRoadmapEarly('show', widget.id)) && !/fit the widget/.test(bbRoadmapEarly('--prompt')),
   'show marks it done rather than sent, and the session prompt carries no step');
ok(/done-step.*step 2 of R\d+  fit the widget/.test(bbRoadmapEarly('history', '-n', '3'))
   && /why: told in chat/.test(bbRoadmapEarly('history', '-n', '3')),
   '...and the log records who finished what, with the note');
// Send step 1, then mark it done: done wins over sent for the frontier.
bbRoadmapEarly('step', 'done', widget.id, '1');
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(id => document.querySelector(
  `#roadmapList .roadmap[data-id="${id}"][data-step="0"]`)?.classList.contains('done'), widget.id);
const widgetAfter = await open();
ok(widgetAfter.find(i => i.text === 'paint it').can
   && widgetAfter.find(i => i.step === '-1' && i.text === 'ship the widget').can,
   'with steps 1 and 2 done, step 3 is the frontier and the group arrow stands for it');
const refusedBy = (...a) => { try { bbRoadmapEarly(...a); return ''; } catch (e) { return String(e.stderr); } };
ok(/gone stays where it is/.test(refusedBy('step', 'mv', widget.id, '1', 'down')),
   'a done step is pinned like a sent one');
ok(/gone stays where it is/.test(refusedBy('step', 'mv', widget.id, '2', 'down')),
   '...by mark, not by prefix');
// The last step finishes the plan: the item leaves the list and the log says
// done, with no second command: a plan with every step done is not "left".
ok(/step 3 of R\d+ done, the last one, so R\d+ is done and off the list/.test(
     bbRoadmapEarly('step', 'done', widget.id, '3')),
   'marking the last step done says the plan is done with it');
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(id => !document.querySelector(`#roadmapList .roadmap[data-id="${id}"]`), widget.id);
ok(!(await open()).some(i => i.text === 'ship the widget'),
   '...and the item is off the list');
{
  const log = bbRoadmapEarly('history', '-n', '3');
  ok(/done-step.*step 3 of R\d+  paint it/.test(log) && new RegExp(`done +R${widget.id}  ship the widget`).test(log),
     '...into the history as done, beside the step that finished it');
}
ok(/nothing dropped as R\d+ is in the history/.test(refusedBy('restore', widget.id)),
   '...and done cannot be put back; it is a session\'s word that the work happened');

// ---- dropped is not gone: put back from the history ------------------------
// Drop is for work that is abandoned, and a decision can be reversed: the
// log carries the row, so restoring brings the plan back as it was (its
// steps, its details, its number), from bb or from the pane's Put back.
bbRoadmapEarly('add', 'a line dropped by mistake', '--step', 'first', '--step', 'second');
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(() => [...document.querySelectorAll('#roadmapList .roadmap .txt')]
  .some(t => t.textContent === 'a line dropped by mistake'));
const dropped = (await open()).find(i => i.text === 'a line dropped by mistake');
bbRoadmapEarly('info', dropped.id, 'the details ride along');
ok(new RegExp(`removed R${dropped.id}; bb roadmap restore R${dropped.id} puts it back`).test(
     bbRoadmapEarly('rm', dropped.id, 'abandoned for now')),
   'dropping names the way back');
ok(new RegExp(`put back R${dropped.id}: a line dropped by mistake`).test(bbRoadmapEarly('restore', dropped.id)),
   'bb roadmap restore puts it back under its own number');
{
  const row = read().projects.alpha.find(r => String(r.id) === String(dropped.id));
  ok(row && row.steps.length === 2 && row.steps[1].text === 'second' && row.info === 'the details ride along',
     '...with its steps and its details as they were');
  // -n 6, not 2: four events in one second sort as they were written.
  ok(/restored +R\d+  a line dropped by mistake/.test(bbRoadmapEarly('history', '-n', '6')),
     '...and the log says it was put back');
  ok(/is on the list/.test(refusedBy('restore', dropped.id)),
     '...and not twice');
}
bbRoadmapEarly('rm', dropped.id, 'dropped again, for the pane');
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(id => !document.querySelector(`#roadmapList .roadmap[data-id="${id}"]`), dropped.id);
if (!(await page.$eval('#roadmapLog', b => b.classList.contains('on')))) await page.click('#roadmapLog');
await page.waitForFunction(id => document.querySelector(`#roadmapHist .hput[data-id="${id}"]`), dropped.id,
                           { timeout: 20000 });
ok(true, 'the history pane offers Put back on the dropped row');
await page.click(`#roadmapHist .hput[data-id="${dropped.id}"]`);
await page.waitForFunction(id => document.querySelector(`#roadmapList .roadmap[data-id="${id}"]`), dropped.id,
                           { timeout: 20000 });
await page.waitForFunction(id => !document.querySelector(`#roadmapHist .hput[data-id="${id}"]`), dropped.id,
                           { timeout: 20000 });
ok((await open()).filter(i => i.id === String(dropped.id)).length === 3,
   '...and one press brings the plan back, both steps under it, and the button goes with it');
await page.click('#sheetClose');
await page.waitForFunction(() => document.querySelector('.nbsheet').hidden, { timeout: 10000 });

// A reload that was already in flight must not take what was typed while it
// was out. Held open with a route so the race is deterministic: it hid for
// weeks as a load-dependent flake (bug #13) precisely because a slow box is
// what puts the reply on the wrong side of the typing.
{
  let release, held = false;
  // Only the FIRST request waits. A handler that holds every one of them
  // would hang every later test in this file the moment it was released.
  await page.route('**/api/roadmap?*', async route => {
    if (!held){ held = true; await new Promise(r => { release = r; }); }
    await route.continue().catch(() => {});
  });
  page.evaluate(() => notebooks.get('alpha').reload());   // held, so not awaited
  await page.waitForFunction(() => true);
  await unroll(page); await page.fill('#roadmapText', 'typed while a reload was out');
  await page.keyboard.press('Enter');
  await page.waitForFunction(
    () => [...document.querySelectorAll('#roadmapList .roadmap .txt')]
            .some(e => e.textContent.includes('typed while a reload was out')));
  release();
  // Long enough that a reply which was going to overwrite has done it,
  // and that the released request has finished before the route goes.
  await new Promise(r => setTimeout(r, patience(1500)));
  await page.unroute('**/api/roadmap?*');
  ok(await page.$$eval('#roadmapList .roadmap .txt',
       es => es.some(e => e.textContent.includes('typed while a reload was out'))),
     'a reload landing after you type does not take what you typed');
}

// ---- keeping up with the other writer ------------------------------------
// The Bugs tab has re-read on a revision from the poll since it was built;
// the Roadmap and Memory views loaded once when the tab opened and then held
// that drawing until it was closed and reopened, which is a long time to be
// looking at a list a session has moved on from (roadmap #26). Guarded, and
// that guard is why they had none: the list on screen may be carrying staged
// changes the server has never seen.
await saveList();
bbRoadmapEarly('add', 'added while the panel was just sitting there');
await refreshUntil(page, () => [...document.querySelectorAll('#roadmapList .roadmap .txt')]
  .some(e => e.textContent.includes('added while the panel was just sitting there')));
ok(true, 'an item a session adds arrives in an open notebook, with nothing touched');
await unroll(page); await page.fill('#roadmapText', 'something staged, and not to be thrown away');
await page.keyboard.press('Enter');
bbRoadmapEarly('add', 'and one more from the session');
await refreshUntil(page, () => true, { timeout: 4000 });
ok(await page.$$eval('#roadmapList .roadmap .txt',
     es => es.some(e => e.textContent.includes('something staged'))
        && !es.some(e => e.textContent.includes('and one more from the session'))),
   '...and does not, while something here is staged; a re-read would take it');
await saveList();
await refreshUntil(page, () => [...document.querySelectorAll('#roadmapList .roadmap .txt')]
  .some(e => e.textContent.includes('and one more from the session')));
ok(true, '...which is why the catch-up waits for Save rather than skipping it');

// ---- two writers, one item ----------------------------------------------
// The panel stages, so what it replays at Save was read some time ago. A
// session rewording the same line meanwhile would have its words taken with
// nobody told, so every op that REPLACES something carries what it believes
// it is replacing, and is refused when that is no longer there (roadmap #26).
const clashId = String(bbRoadmapEarly('add', 'the line two people will write')
  .match(/added R(\d+)/)[1]);
await page.evaluate(() => notebooks.get('alpha').reload());
await page.waitForFunction(i => !!document.querySelector(
  `#roadmapList .roadmap[data-id="${i}"]`), clashId, { timeout: 10000 });
const clashBox = () => page.$eval('#roadmapClash',
  el => el.textContent.replace(/\s+/g, ' '));
// With the poll held for the three steps it takes: a redraw between opening
// the box and pressing its button detaches the button, and the click then
// fails as "element was detached" or waits out its timeout on a node that is
// no longer in the document (B99). The window is these three lines, so
// nothing else in the block loses its poll.
const rewordTo = async (text) => {
  await holdPoll(page);
  try{
    // OPEN TO SAVE IN ONE EVALUATE. Four round trips gave the list four
    // chances to repaint under the box and take it away, which is what this
    // kept failing on: `page.fill` with the textarea gone. holdPoll stops the
    // fifteen-second refresh and not the notebook's own redraw when a revision
    // moves, so holding it was never going to be enough; doing the whole
    // gesture inside one evaluate leaves no gap to lose. The save handler
    // reads the textarea's value directly, so setting it IS the typing here.
    const why = await page.evaluate(({ id, txt }) => {
      const ed = document.querySelector(`#roadmapList .roadmap[data-id="${id}"][data-step="-1"] .ed`);
      if (!ed) return 'no row to reword';
      ed.click();
      const box = document.querySelector('.editbox');
      if (!box) return 'the edit box did not open';
      box.querySelector('textarea').value = txt;
      box.querySelector('.primary').click();
      return '';
    }, { id: clashId, txt: text });
    if (why) throw new Error(`reword: ${why}`);
  } finally { await freePoll(page); }
};
const clashText = () => read().projects.alpha
  .find(r => String(r.id) === clashId).text;
// The band gone AND the save it was part of finished: the same predicate
// saveList waits on, because settling a conflict resumes that save.
const settled = () => page.waitForFunction(() => {
  const b = document.getElementById('roadmapSaveQuiet');
  return document.getElementById('roadmapClash').hidden
         && b.getAttribute('aria-busy') !== 'true' && b.disabled; }, { timeout: 20000 });

await rewordTo("the operator's wording");
// ...and only now does the other writer land, which is the shape of it:
// staged here, written there, saved after.
bbRoadmapEarly('edit', clashId, "the session's wording");
await page.click('#roadmapSaveQuiet');
await page.waitForFunction(() => !document.getElementById('roadmapClash').hidden,
                           { timeout: 15000 });
ok(/changed this while you had it open/.test(await clashBox()),
   'a reword over somebody else\'s words is refused rather than applied');
ok(/the session's wording/.test(await clashBox())
   && /the operator's wording/.test(await clashBox()),
   '...and both are shown, because a refusal that only says no leaves the typing nowhere');
ok(clashText() === "the session's wording", '...with nothing written meanwhile');
// Settling one carries on the save it interrupted, so what is waited for is
// that save finishing; the row on screen already said the operator's wording
// the moment it was staged, and reading the file before the write lands is how
// this assertion first passed for the wrong reason.
await page.click('#clashMine');
await settled();
ok(clashText() === "the operator's wording",
   'Use mine writes over theirs: a decision, made knowing what it replaces');

await rewordTo('a wording that is about to lose');
bbRoadmapEarly('edit', clashId, 'what the session says now');
await page.click('#roadmapSaveQuiet');
await page.waitForFunction(() => !document.getElementById('roadmapClash').hidden,
                           { timeout: 15000 });
await page.click('#clashTheirs');
await settled();
ok(clashText() === 'what the session says now',
   '...and Keep theirs drops the staged wording instead');

// Same item is not the same words. A session attaching details while the
// operator rewords the line is two people doing two things, and the check is
// per field so that it says so; this was built per ROW first, and reported
// exactly this as a conflict with two sides that did not disagree.
await rewordTo('reworded beside the details');
bbRoadmapEarly('info', clashId, 'which files this touches');
await saveList();
const both = read().projects.alpha.find(r => String(r.id) === clashId);
ok(both.text === 'reworded beside the details' && both.info === 'which files this touches',
   'a reword and a details change on one item both land; the check is per field');

// ---- a session writing over words it has not read ------------------------
// The panel's danger is a staged op replayed late; a session's is longer and
// quieter: it read the list when it started, and may write an item from that
// copy an hour later. Same answer in a different shape: it is refused until it
// has read the list again. No --force, because a flag would be the short path.
const asSession = (...a) => execFileSync(BB, ['roadmap', ...a],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws`, BB_ACCOUNT_UID: 'u-test' } }).toString();
asSession('list');
asSession('edit', clashId, 'a session may write what it has read');
ok(clashText() === 'a session may write what it has read',
   'a session that has read the list writes it, and its own write does not count against it');
bbRoadmapEarly('edit', clashId, 'the operator moved it');
let refusal = '';
try { asSession('edit', clashId, 'over the top'); }
catch (e) { refusal = String(e.stderr); }
ok(/changed since you last read it/.test(refusal) && clashText() === 'the operator moved it',
   '...and is refused once somebody else has, with nothing written');
asSession('list');
asSession('edit', clashId, 'read again, then written');
ok(clashText() === 'read again, then written',
   '...re-reading is what clears it, which makes the honest path the short one');
// ...and the panel is told that it went and read, which is the question the
// operator has after changing something. Being TOLD is #27's channel and
// lands on the session's next prompt; this is the act of going to look.
// On the Roadmap's own head row (R222), not over every view.
await refreshUntil(page, () => /read by a session/.test(
  document.getElementById('roadmapRead')?.textContent || ''));
ok(true, "the Roadmap's head row says when a session here last read it");

// ---- the view comes back with a reload; closing the tab forgets it --------
// The strip and the active pane are the saved layout's; which view a
// notebook was on is this browser's, so a reload lands where you were. A
// notebook closed and opened again is a new instance and starts on the
// strip's first view, as it always did.
const nbOn = () => page.evaluate(() =>
  document.querySelector('.pane .nb .nbview:not([hidden])')?.dataset.view);
await nbTab(page, 'bugs');
await page.reload(); await ready(page);
// The pane comes back from the saved layout, which the phone page above
// wrote last; the view is what is under test here, so the tab is focused
// once the layout has been adopted, or the adoption would undo the focus.
await page.waitForFunction(() => tabs.some(x => x.kind === 'notebook'), { timeout: 20000 });
await page.evaluate(() => focusTab(tabs.find(x => x.kind === 'notebook').id));
await nbShown(page);
ok(await nbOn() === 'bugs', 'a reload brings the notebook back on the view it was on');
await page.evaluate(() => hideTab(tabs.find(x => x.kind === 'notebook').id));
await nbGone(page);
await page.evaluate(() => openNotebook('alpha'));
await nbShown(page);
ok(await nbOn() === await page.evaluate(() => document.querySelector('.pane .nb .nbtabs button').dataset.v),
   '...and a notebook closed and opened again starts on the strip\'s first view');

// B198: a batch its session never closes. Killed mid-way, or the container
// restarted under it, it used to disable Save for every person on the project
// for good, with no way out that did not need a shell.
{
  const call = (path, body) => page.evaluate(async ([p, b]) => {
    const r = await fetch(p, b === null ? {} : { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    return { status: r.status, ...(await r.json().catch(() => ({}))) };
  }, [path, body ?? null]);
  const fs = await import('node:fs');
  bbRoadmap('begin');
  const d = read();
  d.batch.alpha.at = Math.floor(Date.now() / 1000) - 31 * 60;
  fs.writeFileSync(FILE, JSON.stringify(d));
  const got = await call('/api/roadmap?project=alpha');
  ok(got.batch?.stale === true, `a batch open past half an hour is reported as stale (${JSON.stringify(got.batch)})`);
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => /never closed it/.test(
    document.getElementById('roadmapBatch')?.textContent || ''), null, { timeout: 20000 });
  ok(await page.evaluate(() => !document.querySelector('.nb')?.classList.contains('held')),
     '...and holds nothing: the banner says so and the notebook is not held');
  await page.click('#roadmapBatchClose');
  await page.waitForFunction(() => document.getElementById('roadmapBatch')?.hidden, null, { timeout: 20000 });
  ok(!read().batch?.alpha, 'an administrator closes it from the banner, which commits what the session wrote');
}

// B199: a panel holding unsaved work stops re-reading, which is right, and
// used to say nothing while it did.
{
  // Onto the Roadmap first: by this point in the file the notebook has been
  // closed and reopened, which lands it on the strip's first view, and the
  // add box is in the DOM there and not on screen.
  await nbTab(page, 'roadmap');
  await page.waitForSelector('#roadmapShow, #roadmapText', { state: 'visible', timeout: 15000 });
  await unroll(page); await page.fill('#roadmapText', 'staged here and not saved');
  await page.keyboard.press('Enter');
  bbRoadmap('add', 'written underneath by somebody else');
  let said = '';
  for (let i = 0; i < 30 && !said; i++){
    await page.evaluate(() => pollRevs());
    await new Promise(r => setTimeout(r, 400));
    said = await page.evaluate(() => { const m = document.getElementById('roadmapMoved');
                                       return m && !m.hidden ? m.textContent : ''; });
  }
  ok(/changed since you loaded it/.test(said),
     `a panel with unsaved work says when the list moved under it, where the Save is (${said || 'nothing said'})`);
  await saveList();
  ok(await page.evaluate(() => !/changed since/.test(document.getElementById('roadmapMoved')?.textContent || '')),
     '...and stops saying it once there is nothing unsaved');
}

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
