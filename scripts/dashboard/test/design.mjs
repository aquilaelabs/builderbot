// The notebook's Design view (design.py, nb-design.js): a project's design
// language and its pages, laid out as labelled blocks on a frame and named
// for what they are for. Staged behind the notebook's Save; the prompts and
// docs/design-language.md are the server's words, which is what bb design
// prints and Send to Claude points a session at.
import { launch, newPage, ok, done, ready, tmuxCapture, URL, DIR } from './lib.mjs';
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const P = 'alpha';
const NB = `.nb:has(#memTitle:text-is("Notebook: ${P}"))`;
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
// Save at the notebook's foot, waited on until the view says it landed:
// the button goes busy at the press, so "disabled" alone is too early.
const saved = async () => {
  await page.click(`${NB} #roadmapSaveQuiet`);
  await page.waitForFunction(() => document.querySelector('.nb #roadmapSaveQuiet')?.disabled
    && !/unsaved/.test(document.querySelector('.nb #dsHint')?.textContent || ''), null, { timeout: 20000 });
  await page.waitForTimeout(300);
};
const api = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, b ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify(b) } : {});
  return { status: r.status, ...(await r.json()) };
}, [path, body]);

// ---- the record, empty --------------------------------------------------------------
{
  const d = await api(`/api/design?project=${P}`);
  ok(d.status === 200 && d.pages.length === 0 && d.language.themes.length === 1 && d.language.themes[0].name === 'Default' && d.language.themes[0].colors.length === 10
     && d.presets.schemes.length >= 12 && d.presets.templates.some(t => t.key === 'dashboard')
     && d.presets.platforms.map(p => p.key).join(',') === 'web,android,ios,linux,macos,windows'
     && d.file.exists === false,
     `a project starts with the default language, no pages and no file, and the vocabulary comes with it (${
        d.presets.schemes.length} schemes, ${d.presets.templates.length} templates)`);
  ok(d.presets.schemes[0].key === 'default' && d.presets.schemes.slice(1).map(s => s.key).join()
       === d.presets.schemes.slice(1).map(s => s.key).sort().join(),
     'the schemes lead with Default and are alphabetical after it');
}

// ---- the view: add a page, lay it out, save ------------------------------------------
await page.evaluate(n => openNotebook(n, 'design'), P);
await page.waitForSelector(`${NB} #dsBody .sect`, { timeout: 20000 });
ok(/no pages yet/.test(await page.$eval(`${NB} #dsHint`, e => e.textContent))
   && await page.$eval(`${NB} #nbFoot`, e => e.checkVisibility()),
   'the view opens on its head row, saying there are no pages, with the notebook\'s Save at its foot');
await page.selectOption(`${NB} #dsTemplate`, 'dashboard');
await page.click(`${NB} #dsAdd`);
await page.waitForSelector(`${NB} [data-dspage] .dsboard .dsblock`, { timeout: 10000 });
const labels = await page.$$eval(`${NB} [data-dspage] .dsblock b`, bs => bs.map(b => b.textContent));
ok(labels.join(',') === 'Header,Card,Card,Card,Chart,List'
   && await page.$eval(`${NB} #roadmapSaveQuiet`, b => !b.disabled),
   `Add page lays the Dashboard template out as blocks on a desktop frame and wakes Save (${labels.join(',')})`);
await page.fill(`${NB} [data-dspage] [data-dsf="name"]`, 'the home dashboard');
await page.waitForFunction(sel => document.querySelector(sel)?.textContent === 'the home dashboard',
                           `.nb [data-dspage] .sect > summary .t`, { timeout: 5000 });
ok(true, 'naming the page names its section: the name is what the page is for');
// Drag: the chart one column to the right, by the pointer.
const blocks = await page.$$(`${NB} [data-dspage] .dsblock`);
await blocks[4].click();
await page.waitForSelector(`${NB} [data-dsselected]`, { timeout: 5000 });
const sel = await page.$(`${NB} [data-dspage] .dsblock.on`);
const r = await sel.boundingBox();
const board = await (await page.$(`${NB} [data-dspage] .dsboard`)).boundingBox();
const cw = (board.width - 12) / 12;
await page.mouse.move(r.x + 20, r.y + 20);
await page.mouse.down();
await page.mouse.move(r.x + 20 + cw * 1.2, r.y + 20, { steps: 6 });
await page.mouse.up();
await page.waitForTimeout(300);
ok(await page.$eval(`${NB} [data-dspage] .dsblock.on`, e => e.style.gridColumn) === '2 / span 8',
   'a block dragged a column to the right moves a column on the grid');
await page.fill(`${NB} [data-dspage] [data-dsb="label"]`, 'orders per day');
await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsblock.on span')?.textContent === 'orders per day', null, { timeout: 5000 });
ok(true, "what a block is for is typed once and shows on the block");
// Keyboard: Shift and an arrow size the focused block.
await page.focus(`${NB} [data-dspage] .dsblock.on`);
await page.keyboard.press('Shift+ArrowUp');
ok(await page.$eval(`${NB} [data-dspage] .dsblock.on`, e => e.style.gridRow) === '4 / span 4',
   'Shift with an arrow key sizes the focused block a row');
await page.keyboard.press('Shift+ArrowDown'); await page.keyboard.press('Shift+ArrowDown');
ok(await page.$eval(`${NB} [data-dspage] .dsblock.on`, e => e.style.gridRow) === '4 / span 5',
   '...and sizing it past the frame\'s edge caps it there rather than sliding it up');
// Send is dead, with the reason on its row, until the design is saved.
const state = () => page.$eval(`${NB} [data-dspage] [data-dsstate]`, e => e.textContent);
ok(/Save first/.test(await state()) && await page.$eval(`${NB} [data-dspage] [data-dssend]`, b => b.disabled),
   `Send to Claude is dead until the design is saved, and the row says so (${await state()})`);
await saved();
const rec = await api(`/api/design?project=${P}`);
const pg = rec.pages[0];
ok(rec.pages.length === 1 && pg.id === 1 && pg.name === 'the home dashboard' && pg.platform === 'web'
   && pg.blocks[4].x === 1 && pg.blocks[4].y === 3 && pg.blocks[4].h === 5 && pg.blocks[4].label === 'orders per day',
   `Save writes the page with its id, its name, its platform and the blocks as arranged (${JSON.stringify(pg.blocks[4])})`);
// The fixture runs a claude-alpha session on the harness's private tmux,
// so once saved there is nothing left in the way.
ok(await state() === '' && await page.$eval(`${NB} [data-dspage] [data-dssend]`, b => !b.disabled),
   `...and once saved, with a session running here, Send is live (${await state()})`);

// ---- the prompt, the server's words ------------------------------------------------
const promptText = await page.$eval(`${NB} [data-dspage] [data-dsprompt]`, e => e.value);
ok(/^Build or restyle the home dashboard to this layout/.test(promptText)
   && /Platform: a responsive web app/.test(promptText)
   && /Chart \(a chart or a meter\): orders per day, in the middle, columns 2 to 9 of 12, rows 4 to 8 of 8/.test(promptText)
   && /accent #3fb950/.test(promptText) && /Type: system-ui, the platform's own sans-serif/.test(promptText),
   `the page's prompt names the page, its platform, each block with what it is for and where, and the language (${promptText.split('\n')[3]})`);

// ---- the language: themes, each a named set of colours ------------------------------
// A theme is a name, dark or light, and colours that are added, changed
// and taken away one by one; a preset fills one with the ten roles.
await page.selectOption(`${NB} [data-dstheme="0"] [data-dst="from"]`, 'moss');
await page.waitForFunction(() => document.querySelector('.nb #dst-0-hex-5')?.value === '#63c98a', null, { timeout: 5000 });
ok(await page.$eval(`${NB} [data-dspage] .dsboard`, e => e.style.backgroundColor.replace(/\s/g, '')) === 'rgb(22,31,27)'
   && await page.$eval(`${NB} [data-dstheme="0"] [data-dst="from"]`, e => e.value) === '',
   'filling a theme from a preset sets its ten colours and repaints the boards in it, and the picker goes back to keeping them');
await page.fill(`${NB} #dst-0-hex-5`, '#ff8800');
await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsblock[data-i="0"]')?.style.backgroundColor === 'rgb(29, 41, 32)', null, { timeout: 5000 }).catch(() => {});
await page.fill(`${NB} #dst-0-name-0`, 'page');
await page.selectOption(`${NB} #dsThemeFrom`, 'paper');
await page.click(`${NB} #dsThemeAdd`);
await page.waitForSelector(`${NB} [data-dstheme="1"]`, { timeout: 5000 });
ok(await page.$eval(`${NB} [data-sect="design:language"] > summary .sst`, e => e.textContent) === '2 themes'
   && await page.$eval(`${NB} #dst-name-1`, e => e.value) === 'Paper' && await page.$eval(`${NB} #dst-mode-1`, e => e.value) === 'light',
   'Add theme adds one from a preset, named for it, light or dark as it is, and the section counts them');
await page.selectOption(`${NB} [data-dspage] [data-dsf="platform"]`, 'android');
await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsboard')?.dataset.frame === 'phone', null, { timeout: 5000 });
const frames = await page.$$eval(`${NB} [data-dspage] [data-dsf="frame"] option`, os => os.map(o => o.value));
ok(frames.join() === 'phone,landscape' && await page.$eval(`${NB} [data-dspage] .dsblock[data-i="4"]`, e => e.style.gridColumn) === '2 / span 5',
   `an Android page has the phone frames only, upright and sideways, and its blocks are clamped into the upright one (${frames.join()})`);
await saved();
const again = await api(`/api/design?project=${P}`);
ok(again.language.themes.length === 2 && again.language.themes[0].colors.find(c => c.name === 'accent')?.hex === '#ff8800'
   && again.language.themes[0].colors[0].name === 'page' && again.language.themes[1].mode === 'light' && again.pages[0].frame === 'phone',
   'the language and the page save together: the changed hex, the renamed colour and the second theme');
// From here rather than the page, so the refusal is not a console error.
const badR = await fetch(URL.replace(/\/$/, '') + '/api/design', { method: 'POST',
  headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' },
  body: JSON.stringify({ project: P, action: 'save', language: { ...again.language, themes: [{ name: 'A', colors: [{ name: 'bg', hex: 'blue' }] }] }, pages: [] }) });
const bad = { status: badR.status, ...(await badR.json()) };
ok(bad.status === 400 && /a colour is #rrggbb/.test(bad.error), `a colour that is not a hex is refused by name (${bad.error})`);

// ---- Send to Claude, into a session ----------------------------------------------------
await page.waitForFunction(() => !document.querySelector('.nb [data-dspage] [data-dssend]')?.disabled, null, { timeout: 10000 });
await page.click(`${NB} [data-dspage] [data-dssend]`);
let typed = '';
for (let i = 0; i < 40 && !/bb design show 1/.test(typed); i++){ await page.waitForTimeout(250); typed = tmuxCapture(`claude-${P}`); }
ok(/From the operator, on the Design view: build or restyle the home dashboard to the saved design\. `bb design show 1` prints/.test(typed),
   'Send to Claude types a short pointer at the saved page into the session, naming what it is for');

// ---- the file, and bb design -----------------------------------------------------------
await page.click(`${NB} #dsWrite`);
await page.waitForFunction(() => /is written and current/.test(document.querySelector('.nb #dsHint')?.textContent || ''), null, { timeout: 10000 });
const file = `${DIR}/ws/${P}/docs/design-language.md`;
const written = existsSync(file) ? readFileSync(file, 'utf8') : '';
ok(/^# The design language/.test(written) && /\| `--accent` \| `#ff8800` \|/.test(written)
   && /### the home dashboard \(Android app\)/.test(written) && /Chart \(a chart or a meter\): orders per day/.test(written),
   'Write the file puts docs/design-language.md in the tree: the tokens as a table, and each page under Pages');
const token = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', P, 'test'],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const bb = (...a) => execFileSync('bash', [`${REPO}/scripts/bb`, 'design', ...a], { encoding: 'utf8',
  env: { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''), BB_TOKEN: token, BB_PROJECT: P,
         XDG_CACHE_HOME: `${DIR}/cache-design` } });
ok(/Default \(dark\), Paper \(light\); system sans/.test(bb()) && /1  the home dashboard  \(android app, phone, 6 blocks\)/.test(bb()),
   `bb design lists the language and the pages (${bb().split('\n')[1].trim()})`);
const shown = await page.$eval(`${NB} [data-dspage] [data-dsprompt]`, e => e.value);
ok(bb('show', '1').trim() === shown.trim() && bb('show', 'the home dashboard') === bb('show', '1')
   && /Platform: an Android app/.test(shown),
   'bb design show prints the prompt the tab shows, by id or by name');
ok(bb('file') === written, 'bb design file prints the file as the notebook wrote it');
let err = '';
try { bb('show', 'nowhere'); } catch (e) { err = String(e.stderr); }
ok(/no page here called 'nowhere'/.test(err), `...and a page that is not there is refused by name (${err.trim()})`);

// ---- beyond the ten: a colour of the design's own, the families, an overlay, a sideways frame
// What ten real projects needed that the first vocabulary had no slot for
// (the survey of 28 Sep): a success colour, a second surface or a chart
// ramp by name, the exact font stacks, a dialog over the page, a phone
// held sideways.
{
  const pre = (await api(`/api/design?project=${P}`)).presets;
  ok(pre.tokens.map(t => t.key).join() === 'bg,panel,ink,dim,line,accent,warn,bad,note,good'
     && pre.kinds.some(k => k.key === 'overlay') && pre.frames.landscape.cols === 12,
     'the vocabulary carries a good role, an overlay kind and a sideways phone frame');
  await page.click(`${NB} [data-dstheme="0"] [data-dstcadd]`);
  await page.waitForSelector(`${NB} [data-dstheme="0"] [data-dstc="10"]`, { timeout: 5000 });
  await page.fill(`${NB} #dst-0-name-10`, 'surface 2');
  await page.fill(`${NB} #dst-0-hex-10`, '#f0efec');
  await page.fill(`${NB} #dst-0-for-10`, 'a second surface tier');
  await page.fill(`${NB} #dsFonts`, 'Inter for text, JetBrains Mono for code');
  await page.selectOption(`${NB} [data-dspage] [data-dsf="frame"]`, 'landscape');
  await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsboard')?.dataset.frame === 'landscape', null, { timeout: 5000 });
  await page.selectOption(`${NB} [data-dspage] [data-dsf="newkind"]`, 'overlay');
  await page.click(`${NB} [data-dspage] [data-dsblockadd]`);
  await page.waitForSelector(`${NB} [data-dspage] .dsblock.on`, { timeout: 5000 });
  await page.fill(`${NB} [data-dspage] [data-dsb="label"]`, 'the card picker');
  await saved();
  const grown = await api(`/api/design?project=${P}`);
  const text = await page.$eval(`${NB} [data-dspage] [data-dsprompt]`, e => e.value);
  ok(grown.language.themes[0].colors.length === 11 && grown.language.themes[0].colors[10].hex === '#f0efec' && grown.language.fonts.startsWith('Inter')
     && grown.pages[0].frame === 'landscape' && grown.pages[0].blocks.some(b => b.kind === 'overlay' && b.label === 'the card picker'),
     'a colour of the design\'s own, the families, a sideways frame and an overlay block all save');
  ok(/Themes, each a set of the same tokens/.test(text) && /The app starts on Default; a theme picker, where the app has one, offers them by name/.test(text)
     && /  Default \(dark, the default\):\n    page #/.test(text) && /    surface 2 #f0efec: a second surface tier/.test(text)
     && /  Paper \(light\):/.test(text) && /set as Inter for text, JetBrains Mono for code/.test(text) && /good #/.test(text)
     && /on a landscape frame \(12 columns by 6 rows\)/.test(text) && /Overlay \(a dialog, sheet, drawer, popover or toast over the page\): the card picker/.test(text),
     'and the prompt says each of them, the themes by name with the default first, and no word on where a picker goes');
  const file = bb('file');
  ok(/### Default \(dark, the default\)/.test(file) && /### Paper \(light\)/.test(file) && /\| `--surface-2` \| `#f0efec` \| a second surface tier \|/.test(file),
     '...as does the file, a table per theme, the colour as a token of its own');
  await page.click(`${NB} [data-dstheme="0"] [data-dstcrm="10"]`);
  await page.waitForFunction(() => !document.querySelector('.nb [data-dstheme="0"] [data-dstc="10"]'), null, { timeout: 5000 });
  await page.click(`${NB} [data-dstheme="1"] [data-dstdefault]`);
  await page.waitForFunction(() => document.querySelector('.nb #dst-name-0')?.value === 'Paper', null, { timeout: 5000 });
  await page.click(`${NB} [data-dstheme="1"] [data-dstrm]`);
  await page.waitForFunction(() => !document.querySelector('.nb [data-dstheme="1"]'), null, { timeout: 5000 });
  await page.fill(`${NB} #dsFonts`, '');
  await saved();
  const back = (await api(`/api/design?project=${P}`)).language;
  ok(back.themes.length === 1 && back.themes[0].name === 'Paper' && back.themes[0].colors.length === 10,
     'Remove takes a colour out, Make default moves a theme first, and Remove theme takes the other away');
  ok(await page.$eval(`${NB} [data-dstheme="0"] [data-dstrm]`, b => b.disabled), '...and the last theme cannot be removed');
}

// ---- a session writes one: bb design json, edited, and bb design save --------------------
// Asked to put a design language into the notebook, a session reads the
// record with json, changes it, and saves it back whole: a page without
// an id is new, one with its id replaces that page.
{
  const rec = JSON.parse(bb('json'));
  ok(rec.language.themes[0].name === 'Paper' && rec.pages.length === 1 && rec.presets.kinds.length > 10,
     'bb design json prints the record with the presets it is drawn from');
  rec.language.themes = [{ name: 'Night', mode: 'dark', colors: Object.entries(rec.presets.schemes.find(s => s.key === 'carbon').colors).map(([name, hex]) => ({ name, hex, means: '' })) },
                         { name: 'Day', mode: 'light', colors: [{ name: 'bg', hex: '#ffffff', means: 'the page' }] }];
  rec.language.rules = 'Every list pages at fifty.';
  rec.pages[0].notes = 'The chart is the first thing read.';
  rec.pages.push({ name: 'the login screen', platform: 'ios', template: 'blank',
                   blocks: [{ kind: 'form', label: 'email, password, one Sign in', x: 0, y: 4, w: 6, h: 4 }] });
  const tmp = `${DIR}/design-save.json`;
  writeFileSync(tmp, JSON.stringify(rec));
  const said = bb('save', tmp);
  const after = await api(`/api/design?project=${P}`);
  ok(/saved alpha's design: 2 pages/.test(said) && after.language.themes.map(t => t.name).join() === 'Night,Day' && after.language.rules === 'Every list pages at fifty.'
     && after.pages[0].id === 1 && after.pages[0].notes === 'The chart is the first thing read.'
     && after.pages[1].id === 2 && after.pages[1].name === 'the login screen' && after.pages[1].frame === 'phone' && after.by === 'session:alpha',
     `a session's bb design save writes the record back: the language, the page by its id, a new page with the next (${said.trim()})`);
  await page.evaluate(n => getNotebook(n).view('design'), P);
  await page.waitForFunction(() => document.querySelectorAll('.nb [data-dspage]').length === 2, null, { timeout: 15000 });
  ok(await page.$eval(`${NB} [data-sect="design:language"] > summary .sst`, e => e.textContent) === '2 themes'
     && await page.$eval(`${NB} [data-dspage="p2"] .sect > summary .t`, e => e.textContent) === 'the login screen',
     '...and the tab shows what the session saved when it is shown again');
  let refused = '';
  try { bb('save', '/nonexistent.json'); } catch (e) { refused = String(e.stderr); }
  ok(/could not read \/nonexistent.json/.test(refused), 'a file that is not there is refused by name');
  await page.click(`${NB} [data-dspage="p2"] [data-dspagerm]`);
  await page.waitForFunction(() => document.querySelectorAll('.nb [data-dspage]').length === 1, null, { timeout: 5000 });
}

// ---- a page removed, and the record put back ------------------------------------------
await page.click(`${NB} [data-dspage] [data-dspagerm]`);
await page.waitForFunction(() => !document.querySelector('.nb [data-dspage]'), null, { timeout: 5000 });
await page.selectOption(`${NB} [data-dstheme="0"] [data-dst="from"]`, 'default');
await page.waitForFunction(() => document.querySelector('.nb #dst-0-hex-0')?.value === '#1a1f26', null, { timeout: 5000 });
await page.click(`${NB} [data-dstheme="1"] [data-dstrm]`);
await page.waitForFunction(() => !document.querySelector('.nb [data-dstheme="1"]'), null, { timeout: 5000 });
await saved();
const gone = await api(`/api/design?project=${P}`);
ok(gone.pages.length === 0 && gone.language.themes.length === 1 && gone.language.themes[0].colors[0].hex === '#1a1f26',
   'Remove page and Save take the page out, and the language goes back to one theme filled from Default');
rmSync(`${DIR}/ws/${P}/docs`, { recursive: true, force: true });
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
