// The shared to-do list: the one surface here that both sides write.
//
// The operator adds an item in the panel, a session adds one through
// `bb todo`, and either can tick it off. The open items are appended to every
// Claude session bb-tty starts, which is the whole point — something noticed
// mid-task and left undone used to live in the conversation and die with it.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
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
const open = () => page.$$eval('#todoList .todo', ts => ts.map(t => ({
  id: t.dataset.id, text: t.querySelector('.txt').textContent,
  done: t.classList.contains('done'),
  claude: !!t.querySelector('.who') })));

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

// ---- ticking -----------------------------------------------------------
await page.click(`#todoList .todo[data-id="${mine.id}"] input`);
await page.waitForFunction(id => document.querySelector(`#todoList .todo[data-id="${id}"]`)
  ?.classList.contains('done'), mine.id);
ok(read().projects.alpha.find(r => String(r.id) === mine.id).done === true,
   'ticking one writes it through');
items = await open();
ok(items[items.length - 1].id === mine.id,
   '...and it sinks below what is still open');

// ---- what a session is told --------------------------------------------
const prompt = execFileSync(BB, ['todo', '--prompt'],
  { env: { ...process.env, BB_TODO_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(prompt.includes('make the picker wrap properly'),
   'the block a session is started with carries the open items');
ok(!prompt.includes('delete a project from the dashboard'),
   '...and not the ticked ones');
ok(/bb todo add/.test(prompt) && /bb todo done/.test(prompt),
   '...and tells it how to add and tick, since that is the half it has to do');

const empty = execFileSync(BB, ['todo', '--prompt'],
  { env: { ...process.env, BB_TODO_PROJECT: 'beta', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(empty === '',
   'a project with an empty list adds nothing to a prompt at all');

// ---- dropping ----------------------------------------------------------
await page.click(`#todoList .todo[data-id="${mine.id}"] .rm`);
await page.waitForFunction(() => document.querySelectorAll('#todoList .todo').length === 1);
ok(read().projects.alpha.length === 1, 'the bin takes it off for good');

// ---- what the server refuses -------------------------------------------
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/todo', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);
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
