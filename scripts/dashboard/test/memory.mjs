// The memory book: the book icon on a project row, the modal behind it, and
// /api/memory. The fixture (run.sh) gives alpha two memories arranged so both
// kinds of index drift are present (one pointer with no file, one file with
// no pointer) because those warnings are the reason to open the thing.
//
// The writes run for real against the scratch home, so this also checks the
// part that matters most: a delete takes the index line out with the file.
import { launch, newPage, ok, done, ready, tmuxCapture, nbShown, nbGone, URL, DIR, openFold, animatedDuring, refreshUntil, closePage, patience, nbGo } from './lib.mjs';
import { readFileSync, existsSync, writeFileSync, mkdirSync } from 'node:fs';

const MEM = `${DIR}/home/.claude/projects/${(DIR + '/ws/alpha').replaceAll('/', '-')}/memory`;
const read = f => readFileSync(`${MEM}/${f}`, 'utf8');

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the way in --------------------------------------------------------
// The icon carries the to-do count (roadmap.mjs covers that); memory rides in
// the same panel, folded under it.
const row = n => `.pgrid .pcard[data-row="${n}"]`;   // the project's card on the Projects page (R218 step 3)
// A locked project keeps its notebook, which is the whole difference from
// the exclusion this replaced, which hid it. It opens read-only.
await page.evaluate(() => openProjectsTab());
await page.waitForSelector(row('delta'), { timeout: 15000 });
ok(await page.$$eval(`${row('delta')} [data-open]`, b => b.length === 1),
   'a locked project still has a page to open');

await page.evaluate(n => openNotebook(n), 'alpha');
await nbShown(page);
await page.waitForFunction(() => document.querySelectorAll('#memList .mem').length === 2);
// Every section opens by default (the operator, 8 Oct: 9fd9ab9), the
// memories with it, the count on the heading. Read once it has finished
// sliding open, since the notebook's draw opens it.
await page.waitForFunction(() => { const d = document.getElementById('memSect');
  return d.open && !d.getAnimations().length; }, null, { timeout: 10000 }).catch(() => {});
ok(await page.$eval('#memSect', d => d.open) && await page.$eval('#memN', e => e.textContent) === '2',
   'the memories start open, with their count on the heading');
await openFold(page, '#memSect');
ok(await page.$eval('#memTitle', el => el.textContent === 'Notebook: alpha'),
   'the panel opens on that project');
// On the strip's FIRST tab, whichever that is: the default is read off the
// strip rather than marked on a button, so reordering the tabs moves it.
ok(await page.$eval('.pane .nb .nbtabs button', b => b.classList.contains('on'))
   && await page.$eval('#memList', el => el.checkVisibility()),
   '...on the first of its tabs, which is what Claude remembers here');
// And with the cursor nowhere: focusing the add-a-line field would raise a
// phone's keyboard over the list the panel just opened to show.
ok(await page.evaluate(() => document.activeElement?.id !== 'roadmapText'),
   '...without putting the cursor in the field and the keyboard over it');
ok(!await page.$eval('#roadmapList', el => el.checkVisibility()),
   '...with the roadmap on its own tab, not in the way of it');
await page.waitForFunction(() => document.getElementById('memList').checkVisibility(),
                           { timeout: 5000 });
ok((await page.$eval('#memWhere', el => el.textContent)).includes('2 memories'),
   'the Memory tab brings them on screen, and says how many there are');

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
// The index is not a document here: it is one line belonging to each memory,
// shown on the memory it names. There is no whole-index editor to get wrong.
ok(await page.$('#memIndex') === null,
   'the index is not offered as a block of text to edit');
// Read, not typed into: the line sits under its label on the memory, and the
// fields for it come only with Edit, the way a bug report's do.
const ixOf = name => page.$eval(`#memList .mem:has(.mname:text-is("${name}")) .bfield .bval`,
  d => d.textContent.replace(/\s+/g, ' ').trim());
ok(await ixOf('tabs') === 'Prefers tabs: spaces are a fight not worth having',
   '...its line is shown on the memory it points at, title and hook');
ok(/not in the index/.test(await ixOf('loose')),
   'a memory with no line says so on the row, which is why Claude misses it');
ok(await page.$('#memList .mem .ix') === null,
   '...and neither row is a form until Edit is pressed');

const drift = await page.$$eval('#memDrift div', ds => ds.map(d => d.textContent));
ok(drift.some(d => d.includes('vanished.md') && d.includes('not here')),
   'an index line pointing at nothing is called out');
ok(drift.some(d => d.includes('loose.md') && d.includes('not in the index')),
   'a memory the index never lists is called out too');
// One heading with the count on it, rather than two orange paragraphs above
// the list: on a phone they were what you scrolled past to reach a memory.
ok(await page.$('#memDrift details[data-sect="memory:drift"]') !== null
   && /2 problems/.test(await page.$eval('#memDrift .sect > summary', e => e.textContent)),
   '...and both sit behind one section that counts them');

// The third kind of drift (roadmap #4): a [[link]] in a memory's body naming
// no memory here, which is what a rename leaves behind. Written to disk the
// way a session writes one, and taken away again so the counts below hold.
{
  const { unlinkSync } = await import('node:fs');
  writeFileSync(`${MEM}/linker.md`, '---\nname: linker\ndescription: points at one that was renamed\nmetadata:\n  type: project\n---\n\nSee [[tabs]] and [[gone-elsewhere]].\n');
  await page.evaluate(() => notebooks.get('alpha').reloadMemory());
  await page.waitForFunction(() => [...document.querySelectorAll('#memDrift div')]
    .some(d => /gone-elsewhere/.test(d.textContent)), null, { timeout: 10000 });
  const drift3 = await page.$$eval('#memDrift div', ds => ds.map(d => d.textContent));
  ok(drift3.some(d => d.includes('linker.md') && d.includes('[[gone-elsewhere]]') && d.includes('names no memory')),
     'a [[link]] in a memory naming no memory here is called out, by file and by link');
  ok(!drift3.some(d => d.includes('[[tabs]]')),
     '...while one that names a memory that exists is not');
  unlinkSync(`${MEM}/linker.md`);
  await page.evaluate(() => notebooks.get('alpha').reloadMemory());
  await page.waitForFunction(() => ![...document.querySelectorAll('#memDrift div')]
    .some(d => /gone-elsewhere/.test(d.textContent)), null, { timeout: 10000 });
}

// The checks below read "the open memory", and every one opens by default
// now (9fd9ab9): the others are shut first, so the open one is the one named.
async function soleMem(name){
  await page.evaluate(n => document.querySelectorAll('#memList .mem[open]').forEach(d => {
    if (d.querySelector('.mname')?.textContent !== n) d.open = false;
  }), name);
  await openFold(page, `#memList .mem:has(.mname:text-is("${name}"))`);
}

// ---- editing -----------------------------------------------------------
await soleMem('tabs');
// Read first, like a bug report: the text under its label, and Edit for the
// fields. Cancel puts them away and drops what was typed.
await page.waitForSelector(`#memList .mem:has(.mname:text-is("tabs")) .mEdit`);
ok(!await page.$(`#memList .mem:has(.mname:text-is("tabs")) textarea[data-file]`)
   && (await page.$eval(`#memList .mem:has(.mname:text-is("tabs")) .mtext`, e => e.textContent)).includes('asked for it twice'),
   'opening one shows the whole file to read, frontmatter and all, and no fields');
await page.click(`#memList .mem:has(.mname:text-is("tabs")) .mEdit`);
await page.waitForSelector(`#memList .mem:has(.mname:text-is("tabs")) textarea[data-file]`);
ok((await page.$eval(`#memList .mem:has(.mname:text-is("tabs")) textarea[data-file]`, t => t.value)).includes('asked for it twice'),
   'Edit puts the file in a field');
ok(await page.$eval('#memSect', d => d.open),
   '...and the Memories section stays open around it, not folded by the redraw Edit makes (B594)');
await page.$eval(`#memList .mem:has(.mname:text-is("tabs")) textarea[data-file]`, t => {
  t.value = t.value.replace('asked for it twice', 'a change nobody wanted');
  t.dispatchEvent(new Event('input'));
});
await page.click(`#memList .mem:has(.mname:text-is("tabs")) .mCancel`);
await page.waitForFunction(() => !document.querySelector('#memList textarea[data-file="tabs.md"]'), null, { timeout: 10000 });
ok((await page.$eval(`#memList .mem:has(.mname:text-is("tabs")) .mtext`, e => e.textContent)).includes('asked for it twice')
   && await page.$eval('[data-ssave="briefing:memories"]', b => b.disabled),
   '...and Cancel puts it away, reading what is on disk, with nothing left to save');
await page.click(`#memList .mem:has(.mname:text-is("tabs")) .mEdit`);
await page.waitForSelector(`#memList .mem:has(.mname:text-is("tabs")) textarea[data-file]`);

await page.$eval(`#memList .mem:has(.mname:text-is("tabs")) textarea[data-file]`, t => {
  t.value = t.value.replace('asked for it twice', 'asked for it three times');
  t.dispatchEvent(new Event('input'));
});
// The Memories section's own Save (the operator, 5 Oct): each section saves
// its own changes. There was one Save for the whole panel at its foot, and on
// a phone it was a long scroll from the memory being edited.
ok(!await page.$eval('[data-ssave="briefing:memories"]', b => b.disabled),
   'typing in a memory arms the Memories section\'s own Save');
await page.click('[data-ssave="briefing:memories"]');
await page.waitForFunction(() => document.querySelector('[data-ssave="briefing:memories"]')
                             .getAttribute('aria-busy') !== 'true',
                           { timeout: 15000 });
ok(read('tabs.md').includes('asked for it three times'),
   'Save writes the edit to the file on disk');
ok(read('tabs.md').startsWith('---\n') && read('tabs.md').endsWith('\n'),
   '...intact, and newline-terminated');
await page.waitForFunction(() => !document.querySelector('#memList textarea[data-file="tabs.md"]'), null, { timeout: 10000 });
ok((await page.$eval(`#memList .mem:has(.mname:text-is("tabs")) .mtext`, e => e.textContent)).includes('asked for it three times'),
   '...and written, the memory reads again, saying what was saved');

// ---- forgetting --------------------------------------------------------
page.dialogs = [];
await page.click(`#memList .mem:has(.mname:text-is("tabs")) [data-del]`);
await page.waitForFunction(() => document.querySelectorAll('#memList .mem').length === 1);
ok(page.dialogs.some(d => d.includes('Forget tabs.md')),
   'forgetting asks first');
ok(!existsSync(`${MEM}/tabs.md`), 'the file is gone');
ok(!read('MEMORY.md').includes('tabs.md') && read('MEMORY.md').includes('vanished.md'),
   '...and its index line went with it, leaving the other lines alone');
ok((await page.$eval('#memWhere', el => el.textContent)).includes('1 memory'),
   'the fold redraws without it');

// ---- a line for a memory that is gone, taken out with one press (B455) ----
// The fold said "saving takes the line out" while Save had nothing staged and
// could not be pressed. It offers the press itself now, and nothing else in
// the index moves.
// One section open at a time in a notebook (the operator, 5 Oct): the
// Index is opened, which closes Memories.
await page.waitForSelector('#memDrift details.sect', { state: 'attached', timeout: 10000 });
await openFold(page, '#memDrift details.sect');
await page.waitForSelector('#memDrift #memTidy', { timeout: 10000 });
ok(/Take it out/.test(await page.$eval('#memDrift #memTidy', b => b.textContent))
   && !(await page.$$eval('#memDrift div', ds => ds.some(d => /saving takes/.test(d.textContent)))),
   'a line pointing at nothing offers Take it out, not a Save that cannot be pressed');
await page.click('#memDrift #memTidy');
await page.waitForFunction(() => !document.querySelector('#memDrift #memTidy'), null, { timeout: 15000 });
ok(!read('MEMORY.md').includes('vanished.md'), '...which takes that line out of the index');

// ---- the index, written from the rows -----------------------------------
// What is left at this point: one memory (loose, unlisted). Filling the
// memory's fields in gives it a line.
await openFold(page, '#memSect');
await soleMem('loose');
await page.click('#memList .mem:has(.mname:text-is("loose")) .mEdit');
await page.waitForSelector('#memList .mem:has(.mname:text-is("loose")) .ixt');
await page.$eval('#memList .mem:has(.mname:text-is("loose")) .ixt', i => {
  i.value = 'Loose ends'; i.dispatchEvent(new Event('input')); });
await page.$eval('#memList .mem:has(.mname:text-is("loose")) .ixh', i => {
  i.value = 'only recall ever surfaced this one'; i.dispatchEvent(new Event('input')); });
ok(!await page.$eval('[data-ssave="briefing:memories"]', b => b.disabled),
   'typing an index line arms the same section\'s Save');
await page.click('[data-ssave="briefing:memories"]');
await page.waitForFunction(() => document.querySelector('[data-ssave="briefing:memories"]')
                             .getAttribute('aria-busy') !== 'true',
                           { timeout: 15000 });
ok(read('MEMORY.md').includes('- [Loose ends](loose.md) \u2014 only recall ever surfaced this one'),
   'saving writes the line, in the shape Claude wrote the others in');
await page.waitForFunction(() => document.querySelectorAll('#memDrift div').length === 0);
ok(true, 'which leaves the panel with nothing to warn about');

// ---- writing one by hand -------------------------------------------------
// It unrolls. The form replaces a one-line link with eight fields, and doing
// that in one frame threw the list under it down the page: the same jump the
// folds, the drop boxes and the card headers all exist not to make. Height,
// like all of them, so the lines below ride down instead of being teleported.
{
  const seen = await animatedDuring(page, async () => {
    await page.click('#memAdd button');
    await page.waitForSelector('#naTitle');
  });
  ok(seen.some(n => /\bmemAdd\b/.test(n)),
     'the memory writer unrolls rather than appearing whole');
}
ok(await page.evaluate(() => document.activeElement?.id !== 'naTitle'),
   'the form opens without a cursor in it, like the rest of this window');
await page.type('#naTitle', 'No parsed progress');
ok(await page.$eval('#naName', i => i.value) === 'no-parsed-progress',
   'the file name follows the title, slugged');
await page.$eval('#naName', i => { i.value = 'my-own-name'; i.dispatchEvent(new Event('input')); });
await page.type('#naTitle', ' here');
ok(await page.$eval('#naName', i => i.value) === 'my-own-name',
   '...and stops following it the moment it is typed in');
await page.$eval('#naName', i => { i.value = 'no-parsed-progress'; i.dispatchEvent(new Event('input')); });
await page.selectOption('#naType', 'feedback');
await page.type('#naHook', 'a word and an ellipsis, never a bar');
await page.type('#naBody', 'Report what it is doing in a word.');
await page.click('#naGo');
await page.waitForFunction(() => document.querySelectorAll('#memList .mem').length === 2);
const born = read('no-parsed-progress.md');
ok(born.startsWith('---\nname: no-parsed-progress\n')
   && born.includes('description: a word and an ellipsis, never a bar')
   && born.includes('metadata:\n  type: feedback\n')
   && born.trimEnd().endsWith('Report what it is doing in a word.'),
   'a memory written by hand comes out in the shape Claude writes them in');
ok(read('MEMORY.md').includes('- [No parsed progress here](no-parsed-progress.md) \u2014 '
                              + 'a word and an ellipsis, never a bar'),
   '...and gets its line in the index in the same act, never one without the other');
ok(await page.$('#naTitle') === null && await page.$('#memAdd button') !== null,
   'the form folds back to the button afterwards');
{
  // ...and folding back is the same motion, in reverse: Cancel and a written
  // memory both roll it up rather than snapping the list upward.
  await page.click('#memAdd button');
  await page.waitForSelector('#naTitle');
  // Open all the way first. A Cancel pressed before the fold has moved at
  // all rolls up from where the box already is, which is no motion, and a
  // loaded box got there (B291).
  await page.waitForFunction(() => !document.getElementById('memAdd').getAnimations().length,
                             null, { timeout: 10000 });
  const seen = await animatedDuring(page, async () => {
    // Pressed in the page: a click Playwright retried after its hit-target
    // check once landed on the button that replaced Cancel, opening the form
    // again (B262, B124's family).
    await page.$eval('#naCancel', b => b.click());
    await page.waitForFunction(() => !document.getElementById('naTitle'));
  });
  ok(seen.some(n => /\bmemAdd\b/.test(n)),
     '...and Cancel rolls it back up, rather than the list jumping to meet it');
}

// ---- the memory log --------------------------------------------------------
// What the notebook changed here, with when. Claude's own memory writes are
// files, not events (the button's tooltip says so), but the dashboard's
// half used to vanish without record: who forgot a memory was nobody.
await page.click('#memLog');
await page.waitForFunction(() => document.querySelectorAll('#memHist .hist').length > 0,
                           { timeout: 10000 });
const macts = await page.$$eval('#memHist .hist .act', as => as.map(a => a.textContent));
ok(macts.includes('forgot') && macts.includes('edited') && macts.includes('wrote'),
   'the memory log carries its verbs: wrote, edited, forgot');
ok(await page.$$eval('#memHist .hist .what', ws => ws.some(w => /tabs\.md/.test(w.textContent))),
   '...naming the file each event touched');
// Closed by the sheet's own Close, not by the button that opened it: the
// sheet covers the whole page now, so that button is behind the overlay,
// which is the point of an overlay, and was the bug. It used to stop at the
// notebook's text column and leave the header reachable through the gap.
await page.evaluate(() => document.querySelector('.nbsheet:not([hidden]) .foot button')
                            ?.click());
await page.waitForFunction(() => !document.querySelector('.nbsheet:not([hidden])'),
                           { timeout: 8000 });
await page.waitForFunction(() => !document.getElementById('memListField').hidden);

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
  ['writing the index as a file, now that it has one writer',
   { action: 'save', project: 'alpha', file: 'MEMORY.md', text: 'x' }],
  ['a new memory whose name is a path',
   { action: 'create', project: 'alpha', name: '../evil', title: 'x',
     hook: 'x', type: 'user', body: 'x' }],
  ['a new memory with a name nobody could have typed',
   { action: 'create', project: 'alpha', name: 'Not A Slug', title: 'x',
     hook: 'x', type: 'user', body: 'x' }],
  ['a new memory of a kind that does not exist',
   { action: 'create', project: 'alpha', name: 'fine-name', title: 'x',
     hook: 'x', type: 'whatever', body: 'x' }],
  ['a new memory with nothing in it',
   { action: 'create', project: 'alpha', name: 'fine-name', title: 'x',
     hook: 'x', type: 'user', body: '  ' }],
  ['a new memory with no line to file it under',
   { action: 'create', project: 'alpha', name: 'fine-name', title: 'x',
     hook: '', type: 'user', body: 'x' }],
  ['a name that is already a memory here',
   { action: 'create', project: 'alpha', name: 'loose', title: 'x',
     hook: 'x', type: 'user', body: 'x' }],
  ['an action nobody offers',
   { action: 'wipe', project: 'alpha' }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
ok(existsSync(`${MEM}/MEMORY.md`) && !existsSync(`${DIR}/home/.claude/evil.md`)
   && !existsSync(`${DIR}/evil.md`) && !existsSync(`${MEM}/../evil.md`)
   && !existsSync(`${MEM}/fine-name.md`),
   'nothing was written outside the memory directory, and no half-refused memory landed');
ok(read('loose.md').includes('Only recall will ever surface this one'),
   'and the memory a duplicate name aimed at is untouched');

// A memory bigger than the editor will take is reported, not truncated.
mkdirSync(MEM, { recursive: true });
writeFileSync(`${MEM}/huge.md`, '---\nname: huge\n---\n' + 'x'.repeat(40000));
await page.evaluate(() => notebooks.get('alpha').reloadMemory());
await page.waitForFunction(() => document.querySelectorAll('#memList .mem').length === 3);
await soleMem('huge');
ok(await page.$eval('#memList .mem:has(.mname:text-is("huge"))',
     l => !l.querySelector('textarea') && l.querySelector('.hint.bad')),
   'an oversized memory gets no editor, and says why');

// Those refusals are 400s by design, and the harness's console collector
// counts every one. Cleared here so the check at the end is about the page.
page.errors = [];

// ...and telling the session is not the Save's job at all any more. It used
// to be: a second button typed the line into the session, because that was
// the only way anything reached one. The prompt hook carries it now (roadmap
// #27), so what this asserts is the silence, and that the counter the hook
// reads from actually moved: the memories are a half of the notebook the
// line has to be able to name.
ok(!/notes about how you work here/.test(tmuxCapture('claude-alpha')),
   'saving a memory spends no line of the session\'s conversation');
ok((JSON.parse(readFileSync(`${DIR}/state/roadmap.json`, 'utf8'))
      .bump?.alpha?.memory || 0) > 0,
   '...and the memory half of the notebook is marked moved, which is what the '
   + 'session is told on its next prompt');

// ---- keeping up with the other writer -----------------------------------
// The stamp on the poll is the directory's own (how many files and how
// lately touched) rather than a counter, because the writer that moves a
// memory most often is a session using its own file tools, which increments
// nothing (roadmap #26).
writeFileSync(`${MEM}/arrived.md`,
  '---\nname: arrived\ndescription: written by a session\nmetadata:\n  type: project\n---\n\nnobody pressed anything\n');
await refreshUntil(page, () => [...document.querySelectorAll('#memList .mname')]
  .some(e => e.textContent === 'arrived'));
ok(true, 'a memory a session writes appears in an open book, with nothing touched');

// ---- a memory that moved under the editor -------------------------------
// The whole-file write is this panel's genuine last-writer-wins, and a memory
// is the largest thing anybody types here, so the editor carries the digest
// of the bytes it loaded, and a save whose base is gone is refused (#26).
// There is no "keep theirs" for this one: the version in the box may be an
// hour of typing, so what is stored is put on screen to read and copy from
// and the two answers are to write over it or to reload deliberately.
writeFileSync(`${MEM}/clash.md`,
  '---\nname: clash\ndescription: two writers\nmetadata:\n  type: project\n---\n\nas loaded\n');
await page.evaluate(() => notebooks.get('alpha').reloadMemory());
await soleMem('clash');
await page.click('#memList .mem:has(.mname:text-is("clash")) .mEdit');
await page.waitForSelector(`#memList .mem:has(.mname:text-is("clash")) textarea[data-file]`);
await page.$eval(`#memList .mem:has(.mname:text-is("clash")) textarea[data-file]`, t => {
  t.value = t.value.replace('as loaded', 'what the operator typed');
  t.dispatchEvent(new Event('input')); });
// A session writing the same file with its own tools, which is the writer
// that passes through nothing this module could count.
writeFileSync(`${MEM}/clash.md`,
  '---\nname: clash\ndescription: two writers\nmetadata:\n  type: project\n---\n\nwhat the session wrote\n');
// Save once it is live (the typing wakes it a tick later) and give the
// refusal's band the patient wait: a flat one ran out under load with the
// save still in flight (B332).
await page.waitForFunction(() => !document.querySelector('[data-ssave="briefing:memories"]').disabled, null, { timeout: patience(10000) });
await page.click('[data-ssave="briefing:memories"]');
await page.waitForFunction(() => !document.getElementById('memClash').hidden,
                           { timeout: patience(30000) });
const memBand = () => page.$eval('#memClash', el => el.textContent.replace(/\s+/g, ' '));
ok(/changed on disk while you had it open/.test(await memBand()),
   'a memory saved over one that moved on disk is refused');
ok(/what the session wrote/.test(await memBand()),
   '...showing what is there now, to read and copy from');
ok(read('clash.md').includes('what the session wrote'), '...with nothing written');
ok((await page.$eval(`#memList .mem:has(.mname:text-is("clash")) textarea[data-file]`, t => t.value))
     .includes('what the operator typed'),
   '...and the typing still in the editor, which is why there is no Keep theirs');
await page.click('#memClashMine');
// Waited on the WRITE, not on the band: Use mine hides the band before it
// posts, so a wait on the band returned while the save was still on its
// way, and the file was read before it landed (B207). The editor closes
// only after the post succeeded and the list has been re-read.
await page.waitForFunction(() => document.getElementById('memClash').hidden
                                 && !document.querySelector('#memList textarea[data-file="clash.md"]'),
                           { timeout: 15000 });
ok(read('clash.md').includes('what the operator typed'),
   'Write mine over it does exactly that, against what is there now');

// ---- who else is in here -------------------------------------------------
// Roadmap #26's other half: a refusal makes a collision safe, and this is
// what stops most of them happening. Both windows are the same ACCOUNT, so
// the account cannot be the answer: the tab's own id is, which is why the
// line can say "your other window" rather than naming you at yourself.
// Nobody else is in this notebook when the block starts. An earlier file's
// window that reloaded holds the old page's seat for the seat's fifty seconds
// (its pagehide leave is sent during unload, which a harness page cannot
// authenticate), and this block is about one window it opens itself (B144).
// Free in a run where nothing came before; a wait for an expiry otherwise.
await refreshUntil(page, () => !/your other window/.test(
  document.getElementById('nbHere').textContent), { timeout: 70000 });
const other = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await other.goto(URL);
await ready(other);
await other.evaluate(n => openNotebook(n), 'alpha');
await nbShown(other);
await refreshUntil(page, () => !document.getElementById('nbHere').hidden);
ok(/your other window/.test(await page.$eval('#nbHere', el => el.textContent)),
   'a second window on the same notebook is named as one, not as somebody else');
await nbGo(other, 'roadmap');
await refreshUntil(page, () => /Roadmap/.test(
  document.getElementById('nbHere').textContent));
ok(true, '...and says which view it is on, which is where the collision would be');
// Leaving for another page is leaving (B765): the project page stays in the
// page model behind Home, and it went on claiming the seat.
await other.evaluate(() => railGo('home'));
await other.evaluate(() => refresh());
await refreshUntil(page, () => document.getElementById('nbHere').hidden
  || !/your other window/.test(document.getElementById('nbHere').textContent));
ok(true, '...and a window that goes to another page is no longer named here');
await other.evaluate(n => openNotebook(n, 'roadmap'), 'alpha');
await nbShown(other);
await other.evaluate(() => refresh());
await refreshUntil(page, () => /your other window/.test(document.getElementById('nbHere').textContent));
ok(true, '...and is again once it comes back');
// Letting go of the notebook says so rather than leaving the seat to time
// out: a line claiming somebody is here who has just left is worse than no
// line. Through destroy(), which is what the tab's ✕ calls; closing the tab
// itself would not do here, because the tab STRIP is per account and shared,
// so shutting it in that window shuts it in this one.
await other.evaluate(() => notebooks.get('alpha').destroy());
// ...and the window then goes, the way a person's does. Without this its tab
// is still in the shared strip, so its next draw made the notebook again and
// the seat came back: the line cleared only if this page polled in between.
await closePage(other);
await refreshUntil(page, () => document.getElementById('nbHere').hidden
  || !/your other window/.test(document.getElementById('nbHere').textContent));
ok(true, '...and goes when that window closes the notebook');

// ---- closing -----------------------------------------------------------
// It is a tab, so it closes the way tabs close and not on a stray Escape.
await page.keyboard.press('Escape');
ok(!!await page.$('.pane .nb'), 'Escape does not dismiss it; a tab is not a dialog');
// The project's page (R218 step 3), its header named for the project.
ok(await page.evaluate(() => tabOf(panes[0])?.kind === 'notebook'
     && /alpha/.test(document.querySelector('#pane0 .bar.proj .pname')?.textContent || '')),
   'it is the page on show, its header named for its project');
await page.evaluate(() => hideTab(tabs.find(t => t.kind === 'notebook').id));
await nbGone(page);
ok(true, '...and closing that tab puts it away');

// B196: two memories added at once. Each create reads MEMORY.md, appends its
// line and writes it back, and nothing held the read and the write together,
// so one rename won and the other memory was left on disk with no index line:
// invisible to every session, which is what create() promises cannot happen.
{
  const mk = name => ({ action: 'create', project: 'alpha', name, title: `T ${name}`,
                        hook: `what ${name} is for`, type: 'user', body: `the body of ${name}` });
  const made = await page.evaluate(bodies => Promise.all(bodies.map(b =>
    fetch('/api/memory', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                           body: JSON.stringify(b) }).then(r => r.json()))),
    [mk('race-one'), mk('race-two'), mk('race-three'), mk('race-four')]);
  const got = await page.evaluate(() => fetch('/api/memory?project=alpha').then(r => r.json()));
  const files = (got.memories || []).map(m => m.file);
  const orphans = (got.issues || []).map(x => x.text).filter(t => /race-.*is not in the index/.test(t));
  ok(made.every(m => !m.error) && ['race-one.md', 'race-two.md', 'race-three.md', 'race-four.md'].every(f => files.includes(f))
     && orphans.length === 0,
     `four memories created at the same moment all get their line in the index (${
       orphans.length ? orphans.join(' | ') : files.filter(f => /^race-/.test(f)).length + ' of 4 listed, none orphaned'})`);
}

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
