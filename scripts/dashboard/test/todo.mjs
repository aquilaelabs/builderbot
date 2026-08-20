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
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/todo', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);
const open = () => page.$$eval('#todoList .todo', ts => ts.map(t => ({
  id: t.dataset.id, step: t.dataset.step, text: t.querySelector('.txt').textContent,
  sent: t.classList.contains('sent'),
  can: !t.querySelector('.go').disabled,
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
ok(read().projects.alpha.length === 1,
   'it lands in /config, not in the project');

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

// ---- sending -----------------------------------------------------------
// The fixture's claude-alpha is a plain shell, which is what makes this
// testable: a shell echoes what is typed into it, which is the exact property
// notify.py uses to decide that Enter is safe.
ok(items.every(i => i.can), 'with a session running, the arrows are live');
await page.click(`#todoList .todo[data-id="${mine.id}"] .go`);
await page.waitForFunction(id => document.querySelector(`#todoList .todo[data-id="${id}"]`)
  ?.classList.contains('sent'), mine.id, { timeout: 15000 });
ok(read().projects.alpha.find(r => String(r.id) === mine.id).sent > 0,
   'sending one marks it sent — the record is what was handed over');
const pane = tmuxCapture('claude-alpha');
ok(pane.includes('delete a project from the dashboard'),
   '...because it really went into the session');
items = await open();
const still = items.find(i => i.id === mine.id);
ok(still.sent && still.can,
   '...and it stays, struck through and still sendable: sent is not done');
ok(items.findIndex(i => i.id === mine.id) === 0,
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
ok(!g.can, 'a group\'s own line sends nothing — its steps are the work');
ok(s1.can && !s2.can,
   'only the next step in line can be sent; the one after it is dead');

await page.click(`#todoList .todo[data-id="${s1.id}"][data-step="0"] .go`);
await page.waitForFunction(id => document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="0"]`)?.classList.contains('sent'),
  s1.id, { timeout: 15000 });
items = await open();
ok(items.find(i => i.text === 'then re-measure it').can,
   'sending the first opens the second, and only then');
ok(items.find(i => i.text === 'widen the select').can,
   '...while the first stays sendable, for when it did not take');
ok(items.findIndex(i => i.text === 'widen the select')
   < items.findIndex(i => i.text === 'then re-measure it'),
   '...and nothing moved');

const skip = await post({ action: 'send', project: 'alpha', id: Number(s2.id), step: 1 });
ok(skip.status === 200, 'the second can now be sent');
const back = await post({ action: 'send', project: 'alpha', id: Number(s1.id), step: 0 });
ok(back.status === 200, 'and the first again — "it did not take" is a real answer');
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

await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="0"] .x`);
await page.waitForFunction(id => document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="0"]`)?.classList.contains('sent'),
  c1.id, { timeout: 10000 });
items = await open();
ok(items.find(i => i.text === 'widen the select').sent,
   'the strike icon crosses a step off without sending it');
ok(items.find(i => i.text === 'then re-measure it').can,
   '...and the next one in the group becomes the one that can go');
const byHand = execFileSync(BB, ['todo', '--prompt'],
  { env: { ...process.env, BB_TODO_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(/crossed off by hand/.test(byHand),
   '...and a session is told it was crossed off, not that it was sent');

await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="0"] .x`);
await page.waitForFunction(id => !document.querySelector(
  `#todoList .todo[data-id="${id}"][data-step="0"]`)?.classList.contains('sent'),
  c1.id, { timeout: 10000 });
items = await open();
ok(!items.find(i => i.text === 'then re-measure it').can,
   'the same icon puts it back, and the group closes up behind it');

// ---- dropping one step out of a plan -----------------------------------
await page.click(`#todoList .todo[data-id="${c1.id}"][data-step="0"] .rm`);
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo[data-step="0"]').length === 1
  && document.querySelectorAll('#todoList .todo[data-step="1"]').length === 0,
  { timeout: 10000 });
items = await open();
ok(!items.some(i => i.text === 'widen the select')
   && items.some(i => i.text === 'then re-measure it'),
   'a step can be dropped out of a group on its own');
ok(items.find(i => i.text === 'then re-measure it').can,
   '...and what was behind it becomes the next in line');
ok(read().projects.alpha.find(r => r.text === 'rework the picker').steps.length === 1,
   '...leaving the rest of the plan intact');

// ---- where the tags sit ------------------------------------------------
ok(await page.$eval('#todoList .todo .body',
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
page.dialogs = [];
await page.click(`#todoList .todo[data-id="${mine.id}"][data-step="-1"] .rm`);
await page.waitForFunction(id => !document.querySelector(`#todoList .todo[data-id="${id}"]`),
                           mine.id, { timeout: 10000 });
ok(page.dialogs.length > 0, 'the bin asks first — it is the only way anything leaves');
ok(!read().projects.alpha.some(r => String(r.id) === mine.id),
   '...and takes it off for good');

// ---- what the server refuses -------------------------------------------
for (const [what, body] of [
  ['a project that does not exist', { action: 'add', project: 'nosuch', text: 'x' }],
  ['a project name that is really a path', { action: 'add', project: '../etc', text: 'x' }],
  ['an empty item', { action: 'add', project: 'alpha', text: '   ' }],
  ['an item nobody has', { action: 'done', project: 'alpha', id: 9999 }],
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

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
