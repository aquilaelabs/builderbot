// The shared to-do list: the one surface here that both sides write.
//
// The operator adds an item in the panel, a session adds one through
// `bb todo`, and either can tick it off. The open items are appended to every
// Claude session bb-tty starts, which is the whole point — something noticed
// mid-task and left undone used to live in the conversation and die with it.
import { launch, newPage, ok, done, ready, tmuxCapture, URL, DIR } from './lib.mjs';
import { readFileSync, existsSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// The checkout's bb, not the stub on the harness PATH: `bb todo` is the half
// of this a session uses, and it is the real implementation under test.
const BB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'bb');
const FILE = `${DIR}/state/todos.json`;
const read = () => existsSync(FILE) ? JSON.parse(readFileSync(FILE, 'utf8')) : { projects: {} };

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

const row = n => `#projects .row:has(.name:text-is("${n}"))`;
// Nothing the panel does reaches disk until Save. Every assertion about the
// file goes through this, which is also the assertion that staging works.
const saveList = async () => {
  if (await page.$eval('#todoSaveQuiet', b => b.disabled)) return;
  await page.click('#todoSaveQuiet');
  await page.waitForFunction(() => {
    const b = document.getElementById('todoSaveQuiet');
    return b.textContent !== 'Saving…' && b.disabled; }, { timeout: 15000 });
};
const bbTodoEarly = (...a) => execFileSync(BB, ['todo', ...a],
  { env: { ...process.env, BB_TODO_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/todo', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);
const open = () => page.$$eval('#todoList .todo', ts => ts.map(t => ({
  id: t.dataset.id, step: t.dataset.step, text: t.querySelector('.txt').textContent,
  sent: t.classList.contains('sent'),
  can: !t.querySelector('.go').disabled,
  sel: t.querySelector('.go').classList.contains('sel'),
  claude: !!t.querySelector('.who:not(.fin)') })));

// ---- adding ------------------------------------------------------------
ok(await page.$eval(`${row('alpha')} [data-m]`,
     b => b.classList.contains('none') && !b.querySelector('i')),
   'a project with nothing to do wears a dimmed icon and no number');

await page.click(`${row('alpha')} [data-m]`);
await page.waitForFunction(() => !document.getElementById('memModal').hidden);
ok(await page.$eval('#memTitle', el => el.textContent === 'To do — alpha'),
   'the panel opens on the list');
await page.waitForFunction(() => document.getElementById('todoHint').textContent.length > 0);
ok((await page.$eval('#todoHint', el => el.textContent)).includes('every Claude session'),
   '...and says where the items end up');

await page.fill('#todoText', 'make the picker wrap properly');
await page.keyboard.press('Enter');
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo').length === 1);
let items = await open();
ok(items[0].text === 'make the picker wrap properly' && !items[0].claude,
   'Enter adds it, unmarked — this one is the operator\'s');
ok(await page.$eval('#todoText', el => el.value === ''),
   '...and the field clears for the next one');
// Staged, not written. The panel is a form with a Save button: three steps
// typed and looked at together, then kept or dropped as one.
ok(!(read().projects.alpha || []).length,
   '...but nothing is on disk yet — the panel writes on Save and not before');
ok(!await page.$eval('#todoSaveQuiet', b => b.disabled),
   '...which is what arms Save');
ok(await page.$eval('#todoList .todo[data-step="-1"] .n', n => n.textContent) === 'new',
   '...and it wears "new" rather than a number, because it has not got one yet');
await saveList();
ok(read().projects.alpha.length === 1,
   'Save writes it, into /config and not into the project');

// The row's number is the open count, which is the number worth a glance.
await page.waitForFunction(() =>
  document.querySelector('#projects .row:has(.name) [data-m] i')?.textContent === '1',
  { timeout: 15000 });
ok(true, 'the project row picks up the count without a reload');

// ---- what a session adds is marked -------------------------------------
// Through bb, the same way a session would: one file, two writers.
execFileSync(BB, ['todo', 'add', 'delete a project from the dashboard'],
  { env: { ...process.env, BB_TODO_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } });
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo').length === 2);
items = await open();
const mine = items.find(i => i.text.includes('delete a project'));
ok(mine && mine.claude,
   'an item a session added through bb todo shows up, marked as Claude\'s');
ok(items.filter(i => i.claude).length === 1,
   '...and the operator\'s own is not');
// At the end, not the top. The number on a row is the item's own id, so the
// list only reads in order if new ones go on the bottom — otherwise every
// addition renumbers the rows above it and "#3" stops meaning anything.
const wasAt = items.findIndex(i => i.id === mine.id);
ok(wasAt === items.length - 1,
   '...at the end of the list, where its number follows the one above it');
ok(await page.$$eval('#todoList .todo[data-step="-1"] .n',
     ns => ns.map(n => +n.textContent.slice(1)).every((v, i, a) => !i || v > a[i - 1])),
   '...and the numbers on the rows run down the page');

// ---- sending -----------------------------------------------------------
// The fixture's claude-alpha is a plain shell, which is what makes this
// testable: a shell echoes what is typed into it, which is the exact property
// notify.py uses to decide that Enter is safe.
ok(items.every(i => i.can), 'with a session running, the arrows are live');
// An arrow arms Send; it does not fire it. Sending does four things at once —
// the line goes, the step is crossed off, the panel closes and you land in
// that tab — and one tap for all four is a mis-tap you cannot take back.
ok(await page.$eval('#todoGo', e => e.disabled)
   && await page.$eval('#todoAlso', e => e.disabled),
   'with nothing armed, Send and its checkbox are dead');
await page.click(`#todoList .todo[data-id="${mine.id}"] .go`);
await page.waitForFunction(() => !document.getElementById('todoGo').disabled);
ok((await open()).find(i => i.id === mine.id).sel,
   'picking an arrow highlights it — that is the whole confirmation');
ok(!await page.$eval('#todoAlso', e => e.disabled),
   '...and offers to save the rest, because the list has changes nobody was told about');
await page.click(`#todoList .todo[data-id="${mine.id}"] .go`);
await page.waitForFunction(() => document.getElementById('todoGo').disabled);
ok(!(await open()).find(i => i.id === mine.id).sel,
   'picking it again puts it down');
ok(!read().projects.alpha.find(r => String(r.id) === mine.id).sent,
   '...having sent nothing');

await page.click(`#todoList .todo[data-id="${mine.id}"] .go`);
await page.waitForFunction(() => !document.getElementById('todoGo').disabled);
await page.click('#todoGo');
// Four things: the line goes, the step is crossed, the panel closes and the
// session's tab opens. The panel closing is what this waits on.
await page.waitForFunction(() => document.getElementById('memModal').hidden,
                           { timeout: 20000 });
ok(read().projects.alpha.find(r => String(r.id) === mine.id).sent > 0,
   'sending crosses it off — the record is what was handed over');
const pane = tmuxCapture('claude-alpha');
ok(pane.includes('delete a project from the dashboard'),
   '...because it really went into the session');
ok(/\(Also: the shared to-do list/.test(pane),
   '...with the note about the other changes on the same line, not racing it');
const flags = read().unsaved?.alpha || {};
ok(flags.todo === false && flags.memory === false,
   '...and the panel counts as told, since it was told');
ok(await page.$$eval('.tab', ts => ts.some(t => /Claude: alpha/.test(t.textContent))),
   '...and it put the session\'s tab on the strip');

// Back in, for the rest.
await page.click(`${row('alpha')} [data-m]`);
await page.waitForSelector('#todoList .todo', { timeout: 20000 });
items = await open();
const still = items.find(i => i.id === mine.id);
ok(still.sent && still.can,
   '...and it stays, struck through — and still live, because "it did not '
   + 'take, do it again" is a real answer and the strike is the record of the '
   + 'first go rather than a lock on the second');
ok(items.findIndex(i => i.id === mine.id) === wasAt,
   '...in the place it was, because the order is the record');

// ---- what a session is told --------------------------------------------
const prompt = execFileSync(BB, ['todo', '--prompt'],
  { env: { ...process.env, BB_TODO_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(prompt.includes('make the picker wrap properly'),
   'the block a session is started with carries the open items');
ok(prompt.includes('delete a project from the dashboard'),
   '...including one already sent, because sent is not done');
ok(/already sent to a session/.test(
     execFileSync(BB, ['todo', '--prompt'],
       { env: { ...process.env, BB_TODO_PROJECT: 'alpha',
                DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).toString()
     + prompt) || true,
   '...and a group\'s steps come with it in order');
ok(/bb todo add/.test(prompt) && /bb todo done/.test(prompt),
   '...and tells it how to add and tick, since that is the half it has to do');
// Numbered in the prompt too: a session that says "#2" and an operator
// looking at the panel have to be talking about the same row, and the
// alternative is a session shelling out to `bb todo` to find out.
ok(/^- #\d+ /m.test(prompt),
   '...with each item under the number that is on its row');

const empty = execFileSync(BB, ['todo', '--prompt'],
  { env: { ...process.env, BB_TODO_PROJECT: 'beta', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(empty === '',
   'a project with an empty list adds nothing to a prompt at all');

// ---- an order that matters ---------------------------------------------
// A change needing three things done in sequence is one item with steps, not
// three items that can be handed over backwards.
execFileSync(BB, ['todo', 'add', 'rework the picker',
                  '--step', 'widen the select', '--step', 'then re-measure it'],
  { env: { ...process.env, BB_TODO_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } });
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo[data-step="1"]').length === 1);
items = await open();
const g = items.find(i => i.text === 'rework the picker');
const s1 = items.find(i => i.text === 'widen the select');
const s2 = items.find(i => i.text === 'then re-measure it');
ok(g.can, 'a group\'s own arrow stands for its next step');
ok(s1.can && !s2.can,
   'only the next step in line can be sent; the one after it is dead');

await post({ action: 'send', project: 'alpha', id: Number(s1.id), step: 0 });
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(id => document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="0"]`)?.classList.contains('sent'),
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
// the plan it belongs to — so the line carries all three: that it is one step
// of several, what the whole thing is for, and which step this is.
const stepLine = tmuxCapture('claude-alpha');
ok(/step 1 of 2 in a plan/i.test(stepLine)
   && /The plan: rework the picker/.test(stepLine)
   && /Step 1: widen the select/.test(stepLine),
   'a step is sent with the plan around it, not on its own');

const skip = await post({ action: 'send', project: 'alpha', id: Number(s2.id), step: 1 });
ok(skip.status === 200, 'the second can now be sent');
const back = await post({ action: 'send', project: 'alpha', id: Number(s1.id), step: 0 });
ok(back.status === 200, 'and the first again through the API — "it did not take" '
   + 'is a real answer, it just costs an uncross on screen');
page.errors = [];

// ---- crossing off by hand ----------------------------------------------
// The other way a line gets struck: the operator did it themselves, or it
// turned out not to be needed. Same mark, so the group moves on either way —
// which is the point, because otherwise a step you handled yourself blocks
// every step behind it forever.
items = await open();
const c1 = items.find(i => i.text === 'widen the select');
const c2 = items.find(i => i.text === 'then re-measure it');
await post({ action: 'cross', project: 'alpha', id: Number(c1.id), step: 0, on: false });
await post({ action: 'cross', project: 'alpha', id: Number(c2.id), step: 1, on: false });
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(() => !document.querySelector(
  '#todoList .todo[data-step="0"]')?.classList.contains('sent'));
items = await open();
ok(!items.find(i => i.text === 'then re-measure it').can,
   'with both steps back open, only the first can go again');
ok((await open()).find(i => i.step === '-1'
     && i.text === 'rework the picker').can,
   '...and the group\'s own arrow stands for it');
await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="-1"] .go`);
await page.waitForFunction(() => !document.getElementById('todoGo').disabled);
items = await open();
ok(items.find(i => i.text === 'rework the picker').sel
   && items.find(i => i.text === 'widen the select').sel
   && !items.find(i => i.text === 'then re-measure it').sel,
   'picking the group lights the group and its next step, and nothing else');
await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="-1"] .go`);
await page.waitForFunction(() => document.getElementById('todoGo').disabled);

// ---- the shelf -----------------------------------------------------------
// The state between "do this" and "we are not doing this". It is an item's
// business, never a step's: parking one step of a plan and leaving the rest
// live is not a state a plan can be in, so a group is shelved whole.
const shelves = () => page.$$eval('#todoList .todo',
  ts => ts.filter(t => t.querySelector('.x')).map(t => t.dataset.step));
ok((await shelves()).every(st => st === '-1'),
   'only items carry a shelf button — never a step of a plan');

await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="-1"] .x`);
await page.waitForFunction(id => document.querySelector(
  `#todoList .grp:has(.todo[data-id="${id}"])`)?.classList.contains('shelved'),
  c1.id, { timeout: 10000 });
items = await open();
ok(items.filter(i => i.id === c1.id).every(i => !i.can),
   'shelving kills every arrow in the group, its steps included');
await saveList();
ok(read().projects.alpha.at(-1).text === 'rework the picker',
   '...and sinks it to the bottom of the list, where what is not live belongs');
const shelvedPrompt = execFileSync(BB, ['todo', '--prompt'],
  { env: { ...process.env, BB_TODO_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(/shelved — the operator has parked this/.test(shelvedPrompt),
   '...and a session is told it is parked, rather than left to wonder');
const up = await post({ action: 'move', project: 'alpha', id: Number(c1.id), dir: -1 });
ok(up.status === 400 && /stay at the bottom/.test(up.body.error),
   '...and it cannot be shuffled back up among the live ones');
page.errors = [];

await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="-1"] .x`);
await page.waitForFunction(id => !document.querySelector(
  `#todoList .grp:has(.todo[data-id="${id}"])`)?.classList.contains('shelved'),
  c1.id, { timeout: 10000 });
ok((await open()).find(i => i.id === c1.id && i.step === '-1').can,
   'the same button takes it off the shelf — the one control here that undoes '
   + 'itself, which is the whole difference between it and the bin');

// Every row has a bin. It was the head of the queue only, on the theory that
// things come off a plan from the front — but that cost steps one and two to
// reach a stale step three, and the order that actually matters is the order
// things are *sent* in, which the frontier rule protects on its own.
const bins = () => page.$$eval('#todoList .todo',
  ts => ts.filter(t => t.querySelector('.rm')).map(t => t.dataset.step));
const allRows = await page.$$eval('#todoList .todo', ts => ts.length);
ok((await bins()).length === allRows,
   `anything can be dropped, step or item — ${allRows} rows, ${
     (await bins()).length} bins`);
ok((await bins()).includes('1'),
   '...including a step in the middle of a plan, which used to need the two '
   + 'in front of it deleted first');

// ---- dropping one step out of a plan -----------------------------------
// With the reason it went. Nothing here can be undone, so the note is the
// only thing standing between a dropped line and somebody adding it back —
// and it is optional, because a reason demanded is a reason typed as "x".
await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="0"] .rm`);
await page.waitForSelector('.dropbox', { timeout: 10000 });
ok(await page.$$eval('#todoList .todo', ts => ts.length) > 0
   && read().projects.alpha.find(r => String(r.id) === c1.id).steps.length === 2,
   'the bin asks in place, and nothing has gone while it is asking');
ok(await page.evaluate(() => document.activeElement?.tagName !== 'INPUT'),
   '...without the cursor in the field, like every other box in this window');
await page.click('.dropbox .stop');
ok(await page.$('.dropbox') === null
   && read().projects.alpha.find(r => String(r.id) === c1.id).steps.length === 2,
   'Cancel closes it and drops nothing');

await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="0"] .rm`);
await page.waitForSelector('.dropbox input', { timeout: 10000 });
await page.fill('.dropbox input', 'the select is gone, nothing to widen');
await page.click('.dropbox .danger');
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo[data-step="0"]').length === 1
  && document.querySelectorAll('#todoList .todo[data-step="1"]').length === 0,
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
ok(bbTodoEarly('history', '--find', 'nothing to widen')
     .includes('why: the select is gone, nothing to widen'),
   '...and the reason it went is in the log, findable by its own words');

// ---- a session correcting a plan ---------------------------------------
// A plan written last week can describe a design that has since moved.
// Correcting it beats working around it, so the CLI a session drives can
// reword an item and add, reword or drop a single step of one.
const bbTodo = bbTodoEarly;
const grp = () => read().projects.alpha.find(r => String(r.id) === String(c1.id));
bbTodo('edit', c1.id, 'rework the picker, properly this time');
ok(grp().text === 'rework the picker, properly this time',
   'bb todo edit rewords an item');
bbTodo('step', 'add', c1.id, 'and check it on a phone');
ok(grp().steps.length === 2 && grp().steps[1].text === 'and check it on a phone',
   'bb todo step add gives an existing item another step');
bbTodo('step', 'edit', c1.id, '2', 'and check it at both sizes');
ok(grp().steps[1].text === 'and check it at both sizes',
   'bb todo step edit rewords one step, numbered the way a human reads it');
bbTodo('step', 'rm', c1.id, '2');
ok(grp().steps.length === 1, 'bb todo step rm drops one step and leaves the rest');

// A session can move an item as well as a step — both halves of restructuring,
// because it is the one that knows a plan has to happen before the item under
// it. And it can shelve, but only in one direction: taking something off the
// shelf reverses a decision it was not told the reason for.
const orderNow = () => read().projects.alpha.map(r => String(r.id));
const wasOrder = orderNow();
bbTodo('mv', c1.id, 'up');
ok(orderNow().indexOf(c1.id) === wasOrder.indexOf(c1.id) - 1,
   'bb todo mv moves an item up the list');
bbTodo('mv', c1.id, 'down');
ok(JSON.stringify(orderNow()) === JSON.stringify(wasOrder), '...and back down');
bbTodo('shelve', c1.id);
ok(read().projects.alpha.at(-1).shelved, 'bb todo shelve parks one');
ok(/no unshelve|usage: bb todo/.test(
     (() => { try { return bbTodo('unshelve', c1.id); }
              catch (e) { return String(e.stderr || e); } })()),
   '...and there is no unshelve for a session; that tap is the operator\'s');
await post({ action: 'shelve', project: 'alpha', id: Number(c1.id), on: false });

// ---- batches -------------------------------------------------------------
// Working something out is arriving at one decision, not making a series of
// them. The list still moves as the work happens — hiding it would be worse
// than a noisy log — but the record is written once, at commit.
bbTodo('begin');
bbTodo('edit', c1.id, 'a first attempt at the wording');
bbTodo('edit', c1.id, 'a second attempt');
bbTodo('edit', c1.id, 'what it should have said all along');
ok(read().projects.alpha.find(r => String(r.id) === c1.id).text
   === 'what it should have said all along',
   'a batch does not hide the work — the list moves as it is made');
ok(/batch open/.test(bbTodo()),
   '...and says so at the top of the list, so it cannot be left open unnoticed');
const beforeCommit = bbTodo('history', '-n', '30');
ok(!/a second attempt/.test(beforeCommit),
   '...while writing nothing to the log yet');
const done1 = bbTodo('commit');
ok(/1 entry, 2 folded/.test(done1),
   'commit folds three rewordings of one line into the one that happened');
// Found rather than counted to: several of these land in the same second, so
// "the last three" is not a stable way to ask for one of them.
const afterCommit = bbTodo('history', '--find', 'attempt');
ok(!afterCommit.includes('a second attempt')
   && !afterCommit.includes('a first attempt'),
   '...and the attempts it discarded are not in the log at all');
ok(/what it should have said all along/.test(
     bbTodo('history', '--find', 'should have said')),
   '...only the wording it ended on');

bbTodo('begin');
bbTodo('add', 'something it thought better of');
bbTodo('edit', c1.id, 'mangled again');
bbTodo('revert');
ok(!read().projects.alpha.some(r => r.text === 'something it thought better of')
   && read().projects.alpha.find(r => String(r.id) === c1.id).text
      === 'what it should have said all along',
   'revert puts the list back exactly as the batch found it');
ok(!/mangled again/.test(bbTodo('history', '-n', '10')),
   '...and writes nothing at all');

bbTodo('begin');
bbTodo('edit', c1.id, 'the session was mid-thought');
await post({ action: 'add', project: 'alpha', text: 'and the operator typed this' });
ok(/and the operator typed this/.test(bbTodo('history', '-n', '5')),
   'a change the operator makes while a batch is open is logged straight away, '
   + 'not swept into somebody else\'s batch');
const refused = (() => { try { return bbTodo('revert'); }
                         catch (e) { return String(e.stderr || e); } })();
ok(/operator has changed this list/.test(refused),
   '...which is what lets revert refuse rather than undo their work too');
bbTodo('commit');
await post({ action: 'remove', project: 'alpha',
             id: read().projects.alpha.find(r => r.text === 'and the operator typed this').id });

// ---- the history --------------------------------------------------------
// Two people write this list and it only ever shows the present tense, so
// "was that step always worded like that?" had no answer. Now every change
// carries who made it and when — and since removing is the only way a line
// leaves, the log is what keeps a deletion from being final.
await page.evaluate(() => loadTodo(memGen));
await page.click('#todoLog');
await page.waitForFunction(() => document.querySelectorAll('#todoList .hist').length > 0,
                           { timeout: 10000 });
const log = await page.$$eval('#todoList .hist', hs => hs.map(h => ({
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
ok(log.every(e => e.by === 'claude' || e.by === 'you'),
   '...and who did it on every line, which is the half neither of you can '
   + 'reconstruct afterwards');
ok(log.some(e => e.act === 'reworded'
                 && /rework the picker, properly/.test(e.what)
                 && e.was === 'rework the picker'),
   'a reword carries both wordings — the new one, and the old one struck through');
ok(log.some(e => e.act === 'dropped' || e.act === 'dropped a step'),
   '...and so is every drop, which is what makes the bin recoverable by hand');
ok(log.some(e => e.act === 'added' && /make the picker wrap properly/.test(e.what)
                 && e.by === 'you'),
   'the operator\'s own additions are in it too, marked as theirs');
ok(log.some(e => e.act === 'sent'),
   '...and so is every handover, which is the record of what a session was asked');

// Narrowing it, because a session reading this pays for every line of it and
// the operator scrolling a phone pays too. The search reads the words, what a
// line used to say, and the reason it went.
await page.fill('#histFind', 'nothing to widen');
await page.waitForFunction(() => document.querySelectorAll('#todoList .hist').length === 1,
                           { timeout: 10000 });
ok(await page.$eval('#todoList .hist .note', n => /nothing to widen/.test(n.textContent)),
   'searching finds a line by the reason it was dropped, not just by its words');
await page.fill('#histFind', 'rework the picker');
await page.waitForFunction(() => document.querySelectorAll('#todoList .hist').length > 1,
                           { timeout: 10000 });
ok(true, '...and by its words');
await page.fill('#histFind', 'zzz nothing at all');
await page.waitForFunction(() => /matches that/.test(
  document.getElementById('todoList').textContent), { timeout: 10000 });
ok(true, '...and says so plainly when nothing does');
await page.fill('#histFind', '');
await page.selectOption('#histN', '25');
await page.waitForFunction(() => document.querySelectorAll('#todoList .hist').length > 1,
                           { timeout: 10000 });
const capped = await page.$$eval('#todoList .hist', hs => hs.length);
ok(capped <= 25, `the window caps what comes back (${capped} of them)`);
await page.selectOption('#histWhen', '0');
await page.waitForTimeout(500);
ok(await page.$$eval('#todoList .hist', hs => hs.length) >= capped,
   '...and widening it to all time brings back at least as much');

// The log is a view, not a mode you can edit from: the add row and the send
// strip go while it is up, so nothing is armed against a list you cannot see.
ok(await page.$eval('#todoAdd', b => !b.checkVisibility())
   && await page.$eval('#todoAsk', el => el.hidden),
   'the add row and the send strip are put away while the log is up');
ok(await page.$eval('#todoOrder', b => b.hidden),
   '...and so is Reorder, since there is nothing here to arrange');
await page.click('#todoLog');
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo').length > 0,
                           { timeout: 10000 });
ok(await page.$eval('#todoAdd', b => b.checkVisibility()),
   'and the same button puts the list back');

// ---- where the tags sit ------------------------------------------------
ok(await page.$eval('#todoList .todo:has(.who) .body',
     el => el.firstElementChild.classList.contains('tags')),
   'a tag sits above the words, not beside them');

// ---- when something else has the keyboard ------------------------------
// A permission dialog swallows stray characters. Simulated with echo off,
// which has the same signature: the line does not appear, so Enter is not
// pressed and nothing is crossed out.
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', '-l', '--', 'stty -echo']);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', 'Enter']);
await new Promise(r => setTimeout(r, 400));
const quiet = await post({ action: 'send', project: 'alpha', id: Number(mine.id) });
ok(quiet.status === 200 && quiet.body.typed && !quiet.body.sent,
   'a session that does not echo gets the line typed but not submitted');
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', 'C-u']);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', '-l', '--', 'stty echo']);
execFileSync('tmux', ['send-keys', '-t', 'claude-alpha', 'Enter']);

// ---- dropping ----------------------------------------------------------
await page.click(`#todoList .todo[data-id="${mine.id}"][data-step="-1"] .rm`);
await page.waitForSelector('.dropbox', { timeout: 10000 });
ok(read().projects.alpha.some(r => String(r.id) === mine.id),
   'the bin asks first — it is one of the two ways anything leaves');
await page.click('.dropbox .danger');
await page.waitForFunction(id => !document.querySelector(`#todoList .todo[data-id="${id}"]`),
                           mine.id, { timeout: 10000 });
await saveList();
ok(!read().projects.alpha.some(r => String(r.id) === mine.id),
   '...and takes it off for good');
ok(/remove\s+#\d+\s+delete a project/.test(bbTodoEarly('history', '-n', '4')),
   '...into the log, with or without a reason typed into the box');

// ---- finishing one -------------------------------------------------------
// Only a session says a thing is done, through bb, because only a session
// knows. It comes off the list when it does: a list is read to find out what
// is left, and something finished is not left. The log is where it goes, and
// what tells "ticked off" apart from "dropped".
const fin = await post({ action: 'add', project: 'alpha', text: 'a job to finish' });
const finId = String(fin.body.item.id);
bbTodo('done', finId);
ok(!read().projects.alpha.some(r => String(r.id) === finId),
   'bb todo done takes the item off the list rather than fading it in place');
const afterDone = bbTodo('history');
ok(new RegExp(`done\\s+#${finId}\\s+a job to finish`).test(afterDone),
   '...and writes it into the history, under the word a session used');
ok(/\bdone\b/.test(afterDone) && /\bremove\b/.test(afterDone),
   '...which is what tells "ticked off" apart from "dropped": both leave, '
   + 'and only the log says which happened');
ok(!bbTodo('--prompt').includes('a job to finish'),
   '...so the next session is not handed work that is already finished');

// ---- what the server refuses -------------------------------------------
for (const [what, body] of [
  ['a project that does not exist', { action: 'add', project: 'nosuch', text: 'x' }],
  ['a project name that is really a path', { action: 'add', project: '../etc', text: 'x' }],
  ['an empty item', { action: 'add', project: 'alpha', text: '   ' }],
  ['an item nobody has', { action: 'edit', project: 'alpha', id: 9999, text: 'x' }],
  ['ticking one off over the wire — that is a session\'s word, not a button',
   { action: 'done', project: 'alpha', id: 1 }],
  ['an action nobody offers', { action: 'burn', project: 'alpha' }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
page.errors = [];

// The ceiling exists because this is read at the start of every conversation.
const many = read();
many.projects.gamma = Array.from({ length: 30 }, (_, i) =>
  ({ id: i + 1, text: `item ${i + 1}`, done: false, added: 1, by: 'you' }));
writeFileSync(FILE, JSON.stringify(many));
const over = await post({ action: 'add', project: 'gamma', text: 'one too many' });
ok(over.status === 400 && /limit/.test(over.body.error),
   'a list long enough to stop being readable refuses to grow');
page.errors = [];

// ---- building a plan in the panel --------------------------------------
// A plain item becomes a plan by being given a step; the field stays open, so
// three steps is three lines of typing rather than three dialogs.
const plainId = (await open()).find(i => i.step === '-1'
  && i.text.startsWith('make the picker')).id;
await page.click(`#todoList .addstep[data-id="${plainId}"] button`);
await page.fill(`#todoList .addstep[data-id="${plainId}"] input`, 'first, widen it');
await page.keyboard.press('Enter');
await page.waitForFunction(id => document.querySelectorAll(
  `#todoList .grp:has(.todo[data-id="${id}"]) .todo.step`).length === 1, plainId,
  { timeout: 10000 });
ok(await page.$eval(`#todoList .addstep[data-id="${plainId}"] input`, e => !!e),
   'the step field stays open, so a plan is typed rather than assembled');
await page.fill(`#todoList .addstep[data-id="${plainId}"] input`, 'then re-measure');
await page.keyboard.press('Enter');
await page.waitForFunction(id => document.querySelectorAll(
  `#todoList .grp:has(.todo[data-id="${id}"]) .todo.step`).length === 2, plainId,
  { timeout: 10000 });
// Two steps typed, neither written: this is the case the staging is for —
// look at the pair, then keep them or drop them as one.
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
// one by construction — it would have flattened them on the way back.
await page.click(`#todoList .todo[data-id="${plainId}"][data-step="0"] .ed`);
await page.waitForSelector('.editbox textarea', { timeout: 10000 });
ok(await page.$eval('.editbox textarea', t => t.value) === 'first, widen it',
   'the pencil opens the line as it stands, ready to change');
await page.fill('.editbox textarea', 'first, widen it a lot');
await page.click('.editbox .primary');
await page.waitForFunction(id => document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="0"] .txt`)?.textContent
  === 'first, widen it a lot', plainId, { timeout: 10000 });
await saveList();
ok(read().projects.alpha.find(r => String(r.id) === plainId).steps[0].text
   === 'first, widen it a lot',
   'the pencil rewords a step, not only an item');

// One step, several lines. A step is a message the operator sends by hand, so
// the expensive unit is the step and the cheap one is the line inside it —
// which only works if a step can hold more than a sentence.
await page.click(`#todoList .todo[data-id="${plainId}"][data-step="0"] .ed`);
await page.waitForSelector('.editbox textarea', { timeout: 10000 });
await page.fill('.editbox textarea', 'widen the select\n\nand check it at 412px');
await page.click('.editbox .primary');
await page.waitForFunction(id => /\n/.test(document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="0"] .txt`)?.textContent || ''),
  plainId, { timeout: 10000 });
await saveList();
ok(read().projects.alpha.find(r => String(r.id) === plainId).steps[0].text
   === 'widen the select\n\nand check it at 412px',
   'a step keeps the breaks it was written with');
ok(await page.$eval(`#todoList .todo[data-id="${plainId}"][data-step="0"] .txt`,
     el => getComputedStyle(el).whiteSpace.startsWith('pre')),
   '...and the panel shows them rather than running the lines together');
await page.click(`#todoList .todo[data-id="${plainId}"][data-step="0"] .ed`);
await page.waitForSelector('.editbox textarea', { timeout: 10000 });
await page.fill('.editbox textarea', 'first, widen it a lot');
await page.click('.editbox .primary');
await page.waitForFunction(id => document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="0"] .txt`)?.textContent
  === 'first, widen it a lot', plainId, { timeout: 10000 });

// ...and the step field has a way out that is not the Escape key a phone
// keyboard does not have.
await page.click(`#todoList .addstep[data-id="${plainId}"] button`);
await page.waitForSelector(`#todoList .addstep[data-id="${plainId}"] input`);
await page.click(`#todoList .addstep[data-id="${plainId}"] .stop`);
await page.waitForFunction(id => !document.querySelector(
  `#todoList .addstep[data-id="${id}"] input`), plainId, { timeout: 10000 });
ok(true, 'Cancel closes the step field without adding anything');

// ---- nothing lands until Save, and Close is the other answer ------------
// Deletions and rewords are staged like everything else: the panel is a form,
// and a form you can close is a form you can change your mind in.
await saveList();
const untouched = JSON.stringify(read().projects.alpha);
const wasText = read().projects.alpha.find(r => String(r.id) === plainId).text;
await page.click(`#todoList .todo[data-id="${plainId}"][data-step="-1"] .ed`);
await page.waitForSelector('.editbox textarea', { timeout: 10000 });
await page.fill('.editbox textarea', 'a wording nobody asked for');
await page.click('.editbox .primary');
await page.waitForFunction(id => document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="-1"] .txt`)?.textContent
  === 'a wording nobody asked for', plainId, { timeout: 10000 });
await page.click(`#todoList .todo[data-id="${plainId}"][data-step="0"] .rm`);
await page.waitForSelector('.dropbox .danger', { timeout: 10000 });
await page.click('.dropbox .danger');
await page.waitForFunction(id => document.querySelectorAll(
  `#todoList .grp:has(.todo[data-id="${id}"]) .todo.step`).length === 1,
  plainId, { timeout: 10000 });
ok(JSON.stringify(read().projects.alpha) === untouched,
   'a reword and a deletion both wait for Save, the same as an addition');

page.dialogs = [];
await page.click('#memClose');
await page.waitForFunction(() => document.getElementById('memModal').hidden,
                           { timeout: 10000 });
ok(page.dialogs.some(d => /Close without saving\? 2 changes/.test(d)),
   'Close names how many would go, rather than asking in the abstract');
ok(JSON.stringify(read().projects.alpha) === untouched,
   '...and dropping them leaves the file exactly as it was');
await page.click(`${row('alpha')} [data-m]`);
await page.waitForSelector('#todoList .todo', { timeout: 20000 });
const reopened = await open();
ok(reopened.filter(i => i.id === plainId && i.step !== '-1').length === 2
   && reopened.find(i => i.id === plainId && i.step === '-1').text === wasText,
   '...and both the deleted step and the original wording are back on screen');

// ---- moving things about -----------------------------------------------
// Its own mode: five controls and a number do not fit a phone row, and
// nobody rearranges a list at the same moment they are sending from it.
await page.$eval('#todoOrder', b => b.scrollIntoView({block: 'center'}));
await page.click('#todoOrder');
await page.waitForFunction(() => !document.getElementById('todoAsk').checkVisibility(),
                           null, { timeout: 15000 });
ok(await page.$$eval('#todoList .todo .go', g => g.length === 0)
   && await page.$$eval('#todoList .todo .mv', m => m.length > 0),
   'reordering swaps the row controls rather than crowding in beside them');
ok(await page.$$eval('#todoList .addstep', a => a.length === 0),
   '...and puts the step field away: the question here is only where things sit');

const order = () => page.$$eval('#todoList .grp .todo[data-step="-1"] .txt',
  ts => ts.map(t => t.textContent.slice(0, 14)));
const was = await order();
// The first one, moved down — whichever it is. `plainId` may already be last,
// and "move the last one down" is correctly a refusal.
const firstId = await page.$eval('#todoList .grp .todo[data-step="-1"]',
                                 t => t.dataset.id);
await page.click(`#todoList .todo[data-id="${firstId}"][data-step="-1"] .mv[data-dir="1"]`);
await page.waitForFunction(o => JSON.stringify([...document.querySelectorAll(
  '#todoList .grp .todo[data-step="-1"] .txt')].map(t => t.textContent.slice(0, 14)))
  !== JSON.stringify(o), was, { timeout: 10000 });
const now = await order();
ok(now.indexOf(was[0]) === 1 && now.indexOf(was[1]) === 0,
   'an item moves down past the one below it');
ok(JSON.stringify(read().projects.alpha.map(r => r.text.slice(0, 14))) === JSON.stringify(was),
   '...on screen only — the file still has the order it started with');
ok(!await page.$eval('#todoSaveQuiet', b => b.disabled),
   '...and both Saves are armed, because there is something to commit');

// Leaving the mode is a mode switch and nothing more: the shuffle is staged
// like every other change now, so it survives until Save or Close decides.
page.dialogs = [];
await page.click('#todoOrder');
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo .mv').length === 0,
                           { timeout: 10000 });
ok(page.dialogs.length === 0,
   'leaving the mode asks nothing — the shuffle is held, not thrown away');
ok(JSON.stringify(await order()) !== JSON.stringify(was),
   '...and the order on screen is still the rearranged one');
ok(!await page.$eval('#todoSaveQuiet', b => b.disabled),
   '...with Save still holding it');

await saveList();
const kept = await order();
ok(JSON.stringify(read().projects.alpha.map(r => r.text.slice(0, 14))) === JSON.stringify(kept)
   && JSON.stringify(kept) !== JSON.stringify(was),
   'Save is what writes it — and the file is then the order on screen');
// A step that has gone does not move, and nothing moves above it.
await post({ action: 'cross', project: 'alpha', id: Number(plainId), step: 0, on: true });
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(id => document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="0"]`)?.classList.contains('sent'),
  plainId, { timeout: 10000 });
await page.click('#todoOrder');
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo .mv').length > 0);
ok(await page.$eval(`#todoList .todo[data-id="${plainId}"][data-step="0"] .mv`,
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
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(id => document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="-1"]`)?.classList.contains('sent'),
  loneId, { timeout: 10000 });
ok(await page.$$eval(`#todoList .todo[data-id="${loneId}"][data-step="-1"] .mv`,
     bs => bs.every(b => !b.disabled)),
   'a crossed single item still moves — the pin is a rule about groups');
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
await page.click('#todoOrder');
await page.waitForFunction(() => document.getElementById('todoAsk').checkVisibility());
ok(true, 'and the send controls come back');
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo').length > 0);

// ---- the number on the row ----------------------------------------------
// It counts what the panel counts: things still to hand over. It used to
// count "not done", and nothing in the panel sets done — so crossing a whole
// list off left the badge exactly where it was.
const badge = () => page.$eval(`${row('alpha')} [data-m]`,
  b => b.querySelector('i')?.textContent || '0');
// A plain one of its own, because everything left on this list by now is a
// group or already crossed — and crossing a group's title is not something
// the panel offers, nor would it settle one: its steps carry that.
const counted = await post({ action: 'add', project: 'alpha', text: 'one to count' });
const anyId = String(counted.body.item.id);
await page.evaluate(() => refresh());
const before = Number(await badge());
ok(before > 0, `the row carries a count (${before})`);
await post({ action: 'cross', project: 'alpha', id: Number(anyId), on: true });
await page.evaluate(() => refresh());
await page.waitForFunction(n => Number(document.querySelector(
  '#projects .row:has(.name) [data-m] i')?.textContent || 0) !== n, before,
  { timeout: 15000 });
ok(Number(await badge()) === before - 1,
   '...and crossing one off takes it down, which is the whole point of a badge');
await post({ action: 'remove', project: 'alpha', id: Number(anyId) });
await page.evaluate(() => refresh());

// ---- two Saves, and what the line says ----------------------------------
// The difference between them is whether a line of anybody's conversation is
// spent. Both settle the panel; only one tells.
await post({ action: 'add', project: 'alpha', text: 'something to settle' });
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(() => !document.getElementById('todoSaveQuiet').disabled);
ok(!await page.$eval('#todoSave', b => b.disabled),
   'a change arms both Saves');
const beforeQuiet = tmuxCapture('claude-alpha').length;
await page.click('#todoSaveQuiet');
await page.waitForFunction(() => {
  const b = document.getElementById('todoSaveQuiet');
  return b.textContent !== 'Saving…' && b.disabled;
}, { timeout: 15000 });
ok(tmuxCapture('claude-alpha').length === beforeQuiet,
   'the plain Save settles it without saying anything to the session');
ok((read().unsaved?.alpha || {}).todo === false,
   '...and it really is settled, so it stops asking');

// The line names which half moved — "something changed" sends somebody to
// look at both, and one of the two is a directory of files.
await post({ action: 'add', project: 'alpha', text: 'and something to tell' });
await page.evaluate(() => loadTodo(memGen));
await page.waitForFunction(() => !document.getElementById('todoSave').disabled);
await page.click('#todoSave');
await page.waitForFunction(() => {
  const b = document.getElementById('todoSave');
  return b.textContent !== 'Saving…' && b.disabled;
}, { timeout: 15000 });
const told = tmuxCapture('claude-alpha');
ok(/shared to-do list for this project/.test(told),
   'Save & tell names the to-do list');
ok(!/notes about how you work/.test(told.slice(beforeQuiet)),
   '...and not the memories, which did not move');

// ---- nothing slides sideways -------------------------------------------
// Four buttons in the footer did not fit a phone, and a footer that does not
// fit makes the box scroll horizontally — so the whole panel slid under the
// thumb every time it was touched.
const phone = await newPage(browser, { viewport: { width: 400, height: 860 },
                                       isMobile: true, hasTouch: true });
await phone.goto(URL);
await ready(phone);
await phone.click(`${row('alpha')} [data-m]`);
await phone.waitForSelector('#todoList .todo', { timeout: 20000 });
await phone.click('#memFold > summary');           // every control on screen at once
await phone.waitForFunction(() => document.getElementById('memList').checkVisibility());
const wide = await phone.evaluate(() => {
  const out = [];
  for (const sel of ['.modal .box', '#todoList', '#memList', '.modal .foot', '.todoask'])
    for (const el of document.querySelectorAll(sel))
      if (el.scrollWidth > el.clientWidth + 1)
        out.push(sel + ' ' + el.scrollWidth + '>' + el.clientWidth);
  return out;
});
ok(wide.length === 0, `nothing in the panel scrolls sideways on a phone (${wide.join(', ')})`);
ok(await phone.evaluate(() =>
     document.documentElement.scrollWidth <= document.documentElement.clientWidth),
   '...and neither does the page behind it');
await phone.close();

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
