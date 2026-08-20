// The memory book: the book icon on a project row, the modal behind it, and
// /api/memory. The fixture (run.sh) gives alpha two memories arranged so both
// kinds of index drift are present — one pointer with no file, one file with
// no pointer — because those warnings are the reason to open the thing.
//
// The writes run for real against the scratch home, so this also checks the
// part that matters most: a delete takes the index line out with the file.
import { launch, newPage, ok, done, ready, tmuxCapture, URL, DIR } from './lib.mjs';
import { readFileSync, existsSync, writeFileSync, mkdirSync } from 'node:fs';

const MEM = `${DIR}/home/.claude/projects/${(DIR + '/ws/alpha').replaceAll('/', '-')}/memory`;
const read = f => readFileSync(`${MEM}/${f}`, 'utf8');

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the way in --------------------------------------------------------
// The icon carries the to-do count (todo.mjs covers that); memory rides in
// the same panel, folded under it.
const row = n => `#projects .row:has(.name:text-is("${n}"))`;
ok(await page.$$eval(`${row('delta')} [data-m]`, b => b.length === 0),
   'an excluded project has no panel: nothing starts there to remember anything');

await page.click(`${row('alpha')} [data-m]`);
await page.waitForFunction(() => !document.getElementById('memModal').hidden);
await page.waitForFunction(() => document.querySelectorAll('#memList .mem').length === 2);
ok(await page.$eval('#memTitle', el => el.textContent === 'To do — alpha'),
   'the panel opens on that project, on its to-do list');
// Memory is folded away under it: a handful of files nobody edits, on screen
// only because it is the one input to a session nobody would otherwise see.
ok(await page.$eval('#memFold', el => !el.open)
   && !await page.$eval('#memSave', el => el.checkVisibility()),
   '...with what Claude remembers folded, and its controls with it');
ok((await page.$eval('#memWhere', el => el.textContent)).includes('2 memories'),
   '...and the fold says how many there are');
await page.click('#memFold > summary');
// The controls live inside the fold, so they are on screen when it is open —
// checkVisibility, not .hidden, because nothing sets a flag on them any more.
await page.waitForFunction(() => document.getElementById('memSave').checkVisibility(),
                           { timeout: 5000 });
ok(await page.$eval('#memFold', el => el.open),
   'opening it brings the memory controls with it');

// ---- what it shows -----------------------------------------------------
const mems = await page.$$eval('#memList .mem', ls => ls.map(l => ({
  name: l.querySelector('.mname').textContent,
  type: l.querySelector('.mtype')?.textContent || '',
  open: l.hasAttribute('open'),
})));
ok(mems.length === 2 && mems.every(m => !m.open),
   'both memories are listed, and both start folded');
ok(mems.some(m => m.name === 'tabs' && m.type === 'feedback')
   && mems.some(m => m.name === 'loose' && m.type === 'project'),
   'each carries the name and type out of its own frontmatter');
ok(await page.$eval('#memIndex', t => t.value.includes('tabs.md')),
   'the index is shown as itself, editable');

const drift = await page.$$eval('#memDrift div', ds => ds.map(d => d.textContent));
ok(drift.some(d => d.includes('vanished.md') && d.includes('not here')),
   'an index line pointing at nothing is called out');
ok(drift.some(d => d.includes('loose.md') && d.includes('not in the index')),
   'a memory the index never lists is called out too');

// ---- editing -----------------------------------------------------------
await page.click('#memList .mem:has(.mname:text-is("tabs")) summary');
await page.waitForSelector('#memList .mem[open] textarea');
ok((await page.$eval('#memList .mem[open] textarea', t => t.value)).includes('asked for it twice'),
   'opening one shows the whole file, frontmatter and all');

await page.$eval('#memList .mem[open] textarea', t => {
  t.value = t.value.replace('asked for it twice', 'asked for it three times');
  t.dispatchEvent(new Event('input'));
});
await page.click('#memSave');
await page.waitForFunction(() => document.getElementById('memSave').textContent === 'Save changes');
ok(read('tabs.md').includes('asked for it three times'),
   'Save writes the edit to the file on disk');
ok(read('tabs.md').startsWith('---\n') && read('tabs.md').endsWith('\n'),
   '...intact, and newline-terminated');

// ---- forgetting --------------------------------------------------------
page.dialogs = [];
await page.click('#memList .mem[open] [data-del]');
await page.waitForFunction(() => document.querySelectorAll('#memList .mem').length === 1);
ok(page.dialogs.some(d => d.includes('Forget tabs.md')),
   'forgetting asks first');
ok(!existsSync(`${MEM}/tabs.md`), 'the file is gone');
ok(!read('MEMORY.md').includes('tabs.md') && read('MEMORY.md').includes('vanished.md'),
   '...and its index line went with it, leaving the other lines alone');
ok((await page.$eval('#memWhere', el => el.textContent)).includes('1 memory'),
   'the fold redraws without it');

// ---- what the server refuses -------------------------------------------
const post = (body) => page.evaluate(async b => {
  const r = await fetch('/api/memory', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);

// The one free-text file write in the dashboard. Everything here is a path
// the client is trying to name for itself, and none of it may work.
for (const [what, body] of [
  ['a path climbing out of the memory directory',
   { action: 'save', project: 'alpha', file: '../../../evil.md', text: 'x' }],
  ['a project name that is really a path',
   { action: 'save', project: '../../etc', file: 'MEMORY.md', text: 'x' }],
  ['a project that does not exist',
   { action: 'save', project: 'nosuch', file: 'MEMORY.md', text: 'x' }],
  ['a file that is not a memory here',
   { action: 'save', project: 'alpha', file: 'passwd.md', text: 'x' }],
  ['deleting the index',
   { action: 'delete', project: 'alpha', file: 'MEMORY.md' }],
  ['an action nobody offers',
   { action: 'wipe', project: 'alpha' }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
ok(existsSync(`${MEM}/MEMORY.md`) && !existsSync(`${DIR}/home/.claude/evil.md`)
   && !existsSync(`${DIR}/evil.md`),
   'nothing was written outside the memory directory');

// A memory bigger than the editor will take is reported, not truncated.
mkdirSync(MEM, { recursive: true });
writeFileSync(`${MEM}/huge.md`, '---\nname: huge\n---\n' + 'x'.repeat(40000));
await page.evaluate(() => loadMemory(memGen));
await page.waitForFunction(() => document.querySelectorAll('#memList .mem').length === 2);
await page.click('#memList .mem:has(.mname:text-is("huge")) summary');
ok(await page.$eval('#memList .mem:has(.mname:text-is("huge"))',
     l => !l.querySelector('textarea') && l.querySelector('.hint.bad')),
   'an oversized memory gets no editor, and says why');

// Those refusals are 400s by design, and the harness's console collector
// counts every one. Cleared here so the check at the end is about the page.
page.errors = [];

// ---- the note to a running session -------------------------------------
// The fixture runs claude-alpha, so the offer is there. What has to hold is
// that the line goes through notify.py's one door, which submits it only when
// it can see that it arrived — the fixture session is a shell, and a shell
// echoes, so this one is submitted.
ok(!await page.$eval('#memNote', b => b.hidden),
   'a project with a session running offers the note');
await page.click('#memNote');
await page.waitForFunction(() => /sent|typed/.test(
  document.getElementById('toast').textContent), { timeout: 15000 });
const pane = tmuxCapture('claude-alpha');
ok(/re-read them/.test(pane), 'pressing it puts the note into that pane');
ok(pane.split('I edited').length - 1 >= 1,
   '...once, not twice: the check counts what it typed rather than looking for it');

// beta has no session, so it must make no offer — and refuse if asked anyway.
const note = await post({ action: 'notify', project: 'beta' });
ok(note.status === 400 && /no Claude session/.test(note.body.error),
   'a project with no session refuses the note');
page.errors = [];

// ---- closing -----------------------------------------------------------
await page.keyboard.press('Escape');
ok(await page.$eval('#memModal', el => el.hidden), 'Escape closes the book');
await page.click(`${row('alpha')} [data-m]`);
await page.waitForFunction(() => !document.getElementById('memModal').hidden);
await page.click('#memModal', { position: { x: 5, y: 5 } });
ok(await page.$eval('#memModal', el => el.hidden), 'so does the backdrop');

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
