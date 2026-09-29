// The notebook's Design view (design.py, nb-design.js): a project's design
// language and its pages, laid out as labeled blocks on a frame and named
// for what they are for. Staged behind the notebook's Save; the prompts and
// docs/design-language.md are the server's words, which is what bb design
// prints. The view is passive: nothing on it reaches into a session.
import { launch, newPage, ok, done, ready, patience, openFold, URL, DIR } from './lib.mjs';
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
  ok(d.status === 200 && d.pages.length === 0 && d.language.themes.length === 0 && d.language.rules.length === 0
     && ['font', 'corners', 'density', 'motion'].every(k => d.language[k] === '')
     && d.presets.schemes.length >= 12 && d.presets.templates.some(t => t.key === 'dashboard')
     && d.presets.platforms.map(p => p.key).join(',') === 'web,android,ios,linux,macos,windows'
     && d.file.exists === false,
     `a project starts with an empty design: no theme, no page, no rule, no choice of type, corners, space or motion, no file, and the vocabulary comes with it (${
        d.presets.schemes.length} schemes, ${d.presets.templates.length} templates)`);
  // Nothing designed beforehand: the briefing says so, and what to do after.
  const pre0 = await api(`/api/preamble?project=${P}`);
  ok(/The notebook's Design view is empty: no theme, no page, no design rule\. Build as you would and choose the look yourself; then put what you arrived at into the design with `bb design save`/.test(pre0.text)
     && /the type, corners, space and motion you settled on/.test(pre0.text)
     && /Under the project's dial Claude may: Add to the design, a save of yours lands\./.test(pre0.text),
     'the briefing of an undesigned project says to build as usual and put the look into the design afterwards, and what the dial does with that');
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
await page.waitForFunction(() => /^the home dashboard \(/.test(document.querySelector('.nb #dsPagePick option:checked')?.textContent || ''), null, { timeout: 5000 });
ok(true, "naming the page names its line on the Pages pulldown: the name is what the page is for");
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
// Dragged a column to the right, the chart partly covers the list beside
// it. A save of that is refused (no two blocks cover the same cells,
// unless one lies wholly inside the other or is an overlay), so the board
// says so as it happens: both outlined in red, and the words under it.
ok(await page.$$eval(`${NB} [data-dspage] .dsblock.clash`, bs => bs.map(b => b.dataset.i).join()) === '4,5'
   && await page.$eval(`${NB} [data-dspage] .dsclash`, e => !e.hidden && /partly cover each other, and Save refuses that/.test(e.textContent)),
   'two blocks that partly cover each other are outlined in red on the board, with the reason under it');
await page.keyboard.press('Shift+ArrowLeft');
ok(await page.$eval(`${NB} [data-dspage] .dsblock.on`, e => e.style.gridColumn) === '2 / span 7'
   && (await page.$$(`${NB} [data-dspage] .dsblock.clash`)).length === 0
   && await page.$eval(`${NB} [data-dspage] .dsclash`, e => e.hidden),
   '...and narrowed by a column it sits beside the list, and the outline and the words go');
// Nothing on the view reaches into a session, and nothing on it is a
// prompt: a session reads the design piece by piece with bb design show
// (the operator, 28 and 29 Sep).
ok(!(await page.$(`${NB} [data-dssend]`)) && !(await page.$(`${NB} button:has-text("Send to Claude")`))
   && !(await page.$(`${NB} #dsBody textarea[readonly]`)) && !(await page.$(`${NB} #dsBody button:has-text("Copy")`)),
   'the view has no Send to Claude, no prompt box and no Copy: it is passive, and read piece by piece');
await saved();
const rec = await api(`/api/design?project=${P}`);
const pg = rec.pages[0];
ok(rec.pages.length === 1 && pg.id === 1 && pg.name === 'the home dashboard' && pg.platform === 'web'
   && pg.blocks[4].x === 1 && pg.blocks[4].y === 3 && pg.blocks[4].h === 5 && pg.blocks[4].label === 'orders per day',
   `Save writes the page with its id, its name, its platform and the blocks as arranged (${JSON.stringify(pg.blocks[4])})`);
// ---- the page's prose, the server's words, read with bb design show --------------------
const promptText = (await api(`/api/design?project=${P}&show=1`)).text || '';
ok(/^Build or restyle the home dashboard to this layout/.test(promptText)
   && /docs\/design-language\.md is yours to write and commit with the work, from what is saved here: `bb design file > docs\/design-language\.md`; the notebook never writes it into the tree by itself/.test(promptText)
   && /Platform: a responsive web app/.test(promptText)
   && /Chart \(a chart or a meter\): orders per day, in the middle, columns 2 to 8 of 12, rows 4 to 8 of 8/.test(promptText)
   && /Colors: none chosen yet\. Choose them as tokens/.test(promptText)
   && /Not chosen yet: type, corners, space, motion\. Choose each from what you build/.test(promptText)
   && !/prefers-reduced-motion|Type:|Shape:|Space:|Motion:|AA contrast/.test(promptText),
   `bb design show PAGE names the page, its platform, each block with what it is for and where, whose the file is, and the language, colors still to choose (${promptText.split('\n')[3]})`);
// A choice nobody made promises nothing (the operator, 29 Sep): "quiet"
// was the default, its sentence ends "none under prefers-reduced-motion",
// and a session reported a stylesheet as falling short of it. The four
// start on "not chosen", and each says what it means once it is chosen.
{
  if (!(await page.$eval(`${NB} [data-sect="design:language"]`, d => d.open))) await openFold(page, `${NB} [data-sect="design:language"]`);
  const first = await page.$$eval(`${NB} #dsFont, ${NB} #dsCorners, ${NB} #dsDensity, ${NB} #dsMotion`,
    ss => ss.map(x => `${x.value}|${x.options[0].textContent}`).join());
  ok(first === '|not chosen,|not chosen,|not chosen,|not chosen',
     `the four choices of the language start on not chosen (${first})`);
  await page.selectOption(`${NB} #dsMotion`, 'quiet');
  await saved();
  const one = (await api(`/api/design?project=${P}&show=1`)).text || '';
  ok(/Motion: short eases on state changes, nothing decorative, and none under prefers-reduced-motion\./.test(one)
     && /Not chosen yet: type, corners, space\. Choose each/.test(one),
     'a choice that is made says what it means, and the ones still open are named as open');
  const pre1 = await api(`/api/preamble?project=${P}`);
  ok(/This project's notebook holds a design already:[^.]*type, corners, space not chosen yet/.test(pre1.text),
     '...and the briefing of a designed project names the choices still open');
  // The briefing a session is started with is the verb's, run as a process
  // of its own: it read no design store and said "empty" of every designed
  // project, while the Briefing tab, asking the server, said otherwise (B355).
  const told = execFileSync('bash', [`${REPO}/scripts/bb`, 'preamble'], { encoding: 'utf8',
    env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws`, BB_PROJECT: P } });
  ok(/This project's notebook holds a design already:/.test(told) && !/Design view is empty/.test(told),
     'bb preamble, which is what a session is started with, says the same of a designed project');
  await page.selectOption(`${NB} #dsFont`, 'system');
  await page.selectOption(`${NB} #dsCorners`, 'soft');
  await page.selectOption(`${NB} #dsDensity`, 'comfortable');
  await saved();
  const all = (await api(`/api/design?project=${P}&show=1`)).text || '';
  ok(/Type: system-ui, the platform's own sans-serif/.test(all) && /Shape: /.test(all) && /Space: /.test(all) && !/Not chosen yet/.test(all),
     '...and with all four chosen nothing is left open');
}

// ---- the language: themes, each a named set of colors ------------------------------
// A theme is a name, dark or light, and colors that are added, changed
// and taken away one by one; a preset fills one with the ten roles.
// No theme yet: the board paints in the page's own colors until one is added.
ok(await page.$eval(`${NB} [data-sect="design:themes"] > summary .sst`, e => e.textContent) === '0 themes'
   && /No theme yet/.test(await page.$eval(`${NB} [data-sect="design:themes"] .hint`, e => e.textContent)),
   'the Themes fold starts empty, saying a session may choose the colors');
await page.selectOption(`${NB} #dsThemeFrom`, 'default');
await page.click(`${NB} #dsThemeAdd`);
await page.waitForSelector(`${NB} [data-dstheme="0"] [data-dst="from"]`, { timeout: 5000 });
await page.selectOption(`${NB} [data-dstheme="0"] [data-dst="from"]`, 'moss');
await page.waitForFunction(() => document.querySelector('.nb #dst-0-hex-5')?.value === '#63c98a', null, { timeout: 5000 });
ok(await page.$eval(`${NB} [data-dspage] .dsboard`, e => e.style.backgroundColor.replace(/\s/g, '')) === 'rgb(22,31,27)'
   && await page.$eval(`${NB} [data-dstheme="0"] [data-dst="from"]`, e => e.value) === '',
   'filling a theme from a preset sets its ten colors and repaints the boards in it, and the picker goes back to keeping them');
await page.fill(`${NB} #dst-0-hex-5`, '#ff8800');
await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsblock[data-i="0"]')?.style.backgroundColor === 'rgb(29, 41, 32)', null, { timeout: 5000 }).catch(() => {});
await page.fill(`${NB} #dst-0-name-0`, 'page');
await page.selectOption(`${NB} #dsThemeFrom`, 'paper');
await page.click(`${NB} #dsThemeAdd`);
await page.waitForSelector(`${NB} [data-dstheme="1"]`, { timeout: 5000 });
ok(await page.$eval(`${NB} [data-sect="design:themes"] > summary .sst`, e => e.textContent) === '2 themes'
   && await page.$eval(`${NB} #dst-name-1`, e => e.value) === 'Paper' && await page.$eval(`${NB} #dst-mode-1`, e => e.value) === 'light'
   && await page.$eval(`${NB} #dsThemePick`, e => e.value === '1' && e.options.length === 2) && !(await page.$(`${NB} [data-dstheme="0"]`)),
   'Add theme adds one from a preset, named for it, light or dark as it is, the Themes section counts them and its pulldown shows the new one alone');
// A frame changed and changed back is where it was (B348): to Phone the
// blocks are clamped into six columns, and back on Desktop they sit where
// they sat, not squeezed.
{
  const places = () => page.$$eval(`${NB} [data-dspage] .dsblock`, bs => bs.map(b => `${b.style.gridColumn} | ${b.style.gridRow}`).join('; '));
  const desk = await places();
  await page.selectOption(`${NB} [data-dspage] [data-dsf="frame"]`, 'phone');
  await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsboard')?.dataset.frame === 'phone', null, { timeout: 5000 });
  const phone = await places();
  await page.selectOption(`${NB} [data-dspage] [data-dsf="frame"]`, 'desktop');
  await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsboard')?.dataset.frame === 'desktop', null, { timeout: 5000 });
  ok(phone !== desk && await places() === desk,
     `a page put on the phone frame and back on the desktop one has its blocks where they were (${desk.split('; ')[4]})`);
  await page.selectOption(`${NB} [data-dspage] [data-dsf="frame"]`, 'phone');
  await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsboard')?.dataset.frame === 'phone', null, { timeout: 5000 });
  ok(await places() === phone, '...and the phone frame keeps its own layout for the next visit');
  await page.selectOption(`${NB} [data-dspage] [data-dsf="frame"]`, 'desktop');
  await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsboard')?.dataset.frame === 'desktop', null, { timeout: 5000 });
  await saved();
  const kept = (await api(`/api/design?project=${P}`)).pages[0];
  ok(kept.frame === 'desktop' && kept.layouts?.phone?.length === kept.blocks.length && kept.layouts.phone.every(r => r.x + r.w <= 6),
     `Save keeps the other frame's layout with the page, one place per block (${JSON.stringify(kept.layouts?.phone?.[4])})`);
}
await page.selectOption(`${NB} [data-dspage] [data-dsf="platform"]`, 'android');
await page.waitForFunction(() => document.querySelector('.nb [data-dspage] .dsboard')?.dataset.frame === 'phone', null, { timeout: 5000 });
const frames = await page.$$eval(`${NB} [data-dspage] [data-dsf="frame"] option`, os => os.map(o => o.value));
ok(frames.join() === 'phone,landscape' && await page.$eval(`${NB} [data-dspage] .dsblock[data-i="4"]`, e => e.style.gridColumn) === '2 / span 5',
   `an Android page has the phone frames only, upright and sideways, and its blocks are clamped into the upright one (${frames.join()})`);
await saved();
const again = await api(`/api/design?project=${P}`);
ok(again.language.themes.length === 2 && again.language.themes[0].colors.find(c => c.name === 'accent')?.hex === '#ff8800'
   && again.language.themes[0].colors[0].name === 'page' && again.language.themes[1].mode === 'light' && again.pages[0].frame === 'phone',
   'the language and the page save together: the changed hex, the renamed color and the second theme');

// ---- nothing takes effect until Save -------------------------------------------------
// Every control here stages (the operator, 29 Sep, and the design language's
// Settings): a changed choice, a theme added, a page added and a rule typed
// leave the record as it is until the foot's Save, and Revert puts the view
// back to what is saved.
{
  const before = await api(`/api/design?project=${P}`);
  await page.selectOption(`${NB} #dsFont`, 'serif');
  await page.selectOption(`${NB} #dsThemeFrom`, 'moss');
  await page.click(`${NB} #dsThemeAdd`);
  await page.waitForSelector(`${NB} [data-dstheme="2"]`, { timeout: 5000 });
  await page.click(`${NB} #dsAdd`);
  await page.waitForFunction(() => document.querySelector('.nb #dsPagePick')?.options.length === 2, null, { timeout: 5000 });
  if (!(await page.$eval(`${NB} [data-sect="design:rules"]`, d => d.open))) await openFold(page, `${NB} [data-sect="design:rules"]`);
  await page.click(`${NB} [data-sect="design:rules"] [data-dsruleadd]`);
  await page.waitForSelector(`${NB} [data-dsrules="lang"] .rulerow.editing .rlName`, { timeout: 5000 });
  await page.fill(`${NB} [data-dsrules="lang"] .rulerow.editing .rlText`, 'A rule that is not saved.');
  await page.waitForTimeout(patience(800));
  const mid = await api(`/api/design?project=${P}`);
  ok(JSON.stringify({ l: mid.language, p: mid.pages }) === JSON.stringify({ l: before.language, p: before.pages })
     && await page.$eval(`${NB} #roadmapSaveQuiet`, b => !b.disabled),
     'a changed choice, a theme added, a page added and a rule typed change nothing on the server until Save, which is awake');
  await page.click(`${NB} #roadmapRevert`);
  await page.waitForFunction(() => document.querySelector('.nb #dsFont')?.value === 'system' && document.querySelector('.nb #dsPagePick')?.options.length === 1, null, { timeout: 10000 });
  ok(await page.$eval(`${NB} [data-sect="design:themes"] > summary .sst`, e => e.textContent) === '2 themes'
     && !(await page.$(`${NB} [data-dsrules="lang"] .rulerow.editing`)) && await page.$eval(`${NB} #roadmapSaveQuiet`, b => b.disabled),
     'Revert puts the view back to what is saved: the choice, the themes, the pages and the rules, and Save sleeps again');
}
// From here rather than the page, so the refusal is not a console error.
const badR = await fetch(URL.replace(/\/$/, '') + '/api/design', { method: 'POST',
  headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' },
  body: JSON.stringify({ project: P, action: 'save', language: { ...again.language, themes: [{ name: 'A', colors: [{ name: 'bg', hex: 'blue' }] }] }, pages: [] }) });
const bad = { status: badR.status, ...(await badR.json()) };
ok(bad.status === 400 && /a color is #rrggbb/.test(bad.error), `a color that is not a hex is refused by name (${bad.error})`);

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
const shown = bb('show', '1');
ok(bb('show', 'the home dashboard') === shown && /^Build or restyle the home dashboard to this layout/.test(shown)
   && /Platform: an Android app/.test(shown),
   'bb design show prints a page by id or by name, the same words');
ok(bb('file') === written, 'bb design file prints the file as the notebook wrote it');
let err = '';
try { bb('show', 'nowhere'); } catch (e) { err = String(e.stderr); }
ok(/no page, theme or rule here called 'nowhere'/.test(err), `...and a page that is not there is refused by name (${err.trim()})`);

// ---- beyond the ten: a color of the design's own, the families, an overlay, a sideways frame
// What ten real projects needed that the first vocabulary had no slot for
// (the survey of 28 Sep): a success color, a second surface or a chart
// ramp by name, the exact font stacks, a dialog over the page, a phone
// held sideways.
{
  const pre = (await api(`/api/design?project=${P}`)).presets;
  ok(pre.tokens.map(t => t.key).join() === 'bg,panel,ink,dim,line,accent,warn,bad,note,good'
     && pre.kinds.some(k => k.key === 'overlay') && pre.frames.landscape.cols === 12,
     'the vocabulary carries a good role, an overlay kind and a sideways phone frame');
  await page.selectOption(`${NB} #dsThemePick`, '0');
  await page.waitForSelector(`${NB} [data-dstheme="0"]`, { timeout: 5000 });
  ok(!(await page.$(`${NB} [data-dstheme="1"]`)), 'the Themes pulldown shows the theme chosen and no other');
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
  const text = bb('show', '1');
  ok(grown.language.themes[0].colors.length === 11 && grown.language.themes[0].colors[10].hex === '#f0efec' && grown.language.fonts.startsWith('Inter')
     && grown.pages[0].frame === 'landscape' && grown.pages[0].blocks.some(b => b.kind === 'overlay' && b.label === 'the card picker'),
     'a color of the design\'s own, the families, a sideways frame and an overlay block all save');
  ok(/Themes, each a set of the same tokens/.test(text) && /The app starts on Default; a theme picker, where the app has one, offers them by name/.test(text)
     && /  Default \(dark, the default\):\n    page #/.test(text) && /    surface 2 #f0efec: a second surface tier/.test(text)
     && /  Paper \(light\):/.test(text) && /set as Inter for text, JetBrains Mono for code/.test(text) && /good #/.test(text)
     && /on a landscape frame \(12 columns by 6 rows\)/.test(text) && /Overlay \(a dialog, sheet, drawer, popover or toast over the page\): the card picker/.test(text),
     'and the prompt says each of them, the themes by name with the default first, and no word on where a picker goes');
  const file = bb('file');
  ok(/### Default \(dark, the default\)/.test(file) && /### Paper \(light\)/.test(file) && /\| `--surface-2` \| `#f0efec` \| a second surface tier \|/.test(file),
     '...as does the file, a table per theme, the color as a token of its own');
  await page.click(`${NB} [data-dstheme="0"] [data-dstcrm="10"]`);
  await page.waitForFunction(() => !document.querySelector('.nb [data-dstheme="0"] [data-dstc="10"]'), null, { timeout: 5000 });
  await page.selectOption(`${NB} #dsThemePick`, '1');
  await page.waitForSelector(`${NB} [data-dstheme="1"]`, { timeout: 5000 });
  await page.click(`${NB} [data-dstheme="1"] [data-dstdefault]`);
  await page.waitForFunction(() => document.querySelector('.nb #dst-name-0')?.value === 'Paper', null, { timeout: 5000 });
  await page.selectOption(`${NB} #dsThemePick`, '1');
  await page.waitForSelector(`${NB} [data-dstheme="1"]`, { timeout: 5000 });
  await page.click(`${NB} [data-dstheme="1"] [data-dstrm]`);
  await page.waitForFunction(() => document.querySelector('.nb #dsThemePick')?.options.length === 1, null, { timeout: 5000 });
  await page.fill(`${NB} #dsFonts`, '');
  await saved();
  const back = (await api(`/api/design?project=${P}`)).language;
  ok(back.themes.length === 1 && back.themes[0].name === 'Paper' && back.themes[0].colors.length === 10,
     'Remove takes a color out, Make default moves a theme first, and Remove theme takes the other away');
  ok(await page.$eval(`${NB} [data-dstheme="0"] [data-dstrm]`, b => !b.disabled), '...and the last theme can go too: no theme is a state a design may be in');
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
  rec.language.rules = [{ name: 'Lists', text: 'Every list pages at fifty.', words: 'list, paging' }, { name: 'voice', text: 'One sentence that tells the person what to do.' }];
  rec.pages[0].notes = 'The chart is the first thing read.';
  rec.pages.push({ name: 'the login screen', platform: 'ios', template: 'blank',
                   blocks: [{ kind: 'form', label: 'email, password, one Sign in', x: 0, y: 4, w: 6, h: 4 }] });
  const tmp = `${DIR}/design-save.json`;
  writeFileSync(tmp, JSON.stringify(rec));
  const said = bb('save', tmp);
  const after = await api(`/api/design?project=${P}`);
  ok(/saved alpha's design: 2 pages/.test(said) && after.language.themes.map(t => t.name).join() === 'Night,Day' && after.language.rules.map(r => r.name).join() === 'lists,voice'
     && after.pages[0].id === 1 && after.pages[0].notes === 'The chart is the first thing read.'
     && after.pages[1].id === 2 && after.pages[1].name === 'the login screen' && after.pages[1].frame === 'phone' && after.by === 'session:alpha',
     `a session's bb design save writes the record back: the language, the page by its id, a new page with the next (${said.trim()})`);
  await page.evaluate(n => getNotebook(n).view('design'), P);
  await page.waitForFunction(() => document.querySelector('.nb #dsPagePick')?.options.length === 2, null, { timeout: 15000 });
  ok(await page.$eval(`${NB} [data-sect="design:themes"] > summary .sst`, e => e.textContent) === '2 themes'
     && /^the login screen \(/.test(await page.$eval(`${NB} #dsPagePick option[value="p2"]`, e => e.textContent))
     && await page.$eval(`${NB} [data-sect="design:pages"] > summary .sst`, e => e.textContent) === '2 pages',
     '...and the tab shows what the session saved when it is shown again: two themes, and the new page on the Pages pulldown');
  let refused = '';
  try { bb('save', '/nonexistent.json'); } catch (e) { refused = String(e.stderr); }
  ok(/could not read \/nonexistent.json/.test(refused), 'a file that is not there is refused by name');
  await page.selectOption(`${NB} #dsPagePick`, 'p2');
  await page.waitForSelector(`${NB} [data-dspage="p2"] .dsboard`, { timeout: 5000 });
  ok(!(await page.$(`${NB} [data-dspage="p1"]`)), 'the Pages pulldown shows the page chosen and no other');
  await page.click(`${NB} [data-dspage="p2"] [data-dspagerm]`);
  await page.waitForFunction(() => document.querySelector('.nb #dsPagePick')?.options.length === 1 && document.querySelector('.nb [data-dspage="p1"]'), null, { timeout: 5000 });
  ok(true, 'Remove page takes it off the pulldown, which shows the first page again');
}

// ---- the design's rules reach a session the way house rules do ---------------------------
// A rule with a trigger is named in the briefing and arrives on its turn
// (rules.matching, through the hooks); one without stands in every
// briefing whole. bb rules show reads it like any rule; bb design show too.
{
  const rulesOut = execFileSync('bash', [`${REPO}/scripts/bb`, 'rules', '--json'], { encoding: 'utf8',
    env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: P } });
  const eff = JSON.parse(rulesOut);
  ok(eff.some(r => r.name === 'lists' && r.design && r.words.join() === 'list,paging'),
     'a design rule is among the rules a session works under, marked as the design\'s, with its triggers');
  const pre = await api(`/api/preamble?project=${P}`);
  ok(/  lists: list, paging \(the design's: bb design show reads it/.test(pre.text) && /One sentence that tells the person what to do\. \(the design's/.test(pre.text)
     && !/Every list pages at fifty/.test(pre.text),
     'the briefing names the triggered rule and how to read it, carries the standing one whole, and never the triggered one\'s text');
  ok(/^lists \(applies to: list, paging\)\n\nEvery list pages at fifty\./.test(bb('show', 'lists')),
     `bb design show NAME prints one rule with what fires it (${bb('show', 'lists').split('\n')[0]})`);
  // In the view: the Rules fold is the Briefing's list, a row a rule, folded,
  // Add a rule first, and a new row is its form until it has words.
  await page.evaluate(n => getNotebook(n).view('design'), P);
  await page.waitForFunction(() => document.querySelectorAll('.nb [data-dsrules="lang"] .rulerow').length === 2, null, { timeout: 15000 });
  if (!(await page.$eval(`${NB} [data-sect="design:rules"]`, d => d.open))) await openFold(page, `${NB} [data-sect="design:rules"]`);
  ok(await page.$(`${NB} [data-sect="design:language"] [data-sect="design:rules"]`) && !(await page.$(`${NB} #dsBody > [data-sect="design:rules"]`)),
     "the language's rules are a section inside the Design language fold, not a fold below everything");
  ok(await page.$eval(`${NB} [data-dsrules="lang"] .rulerow[data-i="1"] .btitle`, e => e.textContent) === 'voice'
     && await page.$eval(`${NB} [data-dsrules="lang"] .rulerow[data-i="0"] .rlkind`, e => e.textContent) === 'on its triggers'
     && await page.$eval(`${NB} [data-dsrules="lang"] .rulerow[data-i="1"] .rlkind`, e => e.textContent) === 'every session'
     && !(await page.$eval(`${NB} [data-dsrules="lang"] .rulerow[data-i="1"]`, e => e.open)),
     "the Rules fold lists them as the Briefing does: a folded row each, its name and when it reaches a session");
  await page.click(`${NB} [data-dsrules="lang"] .rulerow[data-i="1"] summary`);
  await page.waitForFunction(() => { const d = document.querySelector('.nb [data-dsrules="lang"] .rulerow[data-i="1"]'); return d?.open && !d.getAnimations({subtree: true}).length; }, null, { timeout: 10000 });
  ok(/One sentence that tells the person what to do/.test(await page.$eval(`${NB} [data-dsrules="lang"] .rulerow[data-i="1"] .rlBody`, e => e.textContent))
     && await page.$(`${NB} [data-dsrules="lang"] .rulerow[data-i="1"] .rlEdit`),
     'a row opens to be read, with Edit and Remove under it');
  await page.click(`${NB} [data-sect="design:rules"] [data-dsruleadd]`);
  await page.waitForSelector(`${NB} [data-dsrules="lang"] .rulerow[data-i="2"].editing .rlName`, { timeout: 5000 });
  const newRow = `${NB} [data-dsrules="lang"] .rulerow[data-i="2"]`;
  await page.fill(`${newRow} .rlName`, 'Tap targets');
  await page.fill(`${newRow} .rlWords`, 'tap, phone');
  await page.fill(`${newRow} .rlPaths`, 'scripts/dashboard');
  await page.fill(`${newRow} .rlText`, 'Every button on a touch screen is a thumb high.');
  ok(await page.$eval(`${newRow} .btitle`, e => e.textContent) === 'Tap targets' && await page.$eval(`${newRow} .rlkind`, e => e.textContent) === 'on its triggers',
     "typing into the form names the row and says it arrives on its triggers, without a redraw");
  await saved();
  const now = (await api(`/api/design?project=${P}`)).language.rules;
  ok(now.length === 3 && now[2].name === 'tap-targets' && now[2].words.join() === 'tap,phone' && now[2].paths.join() === 'scripts/dashboard',
     `a rule typed in the view saves with its slug name and triggers (${JSON.stringify(now[2]).slice(0, 90)})`);
  const bad = await fetch(URL.replace(/\/$/, '') + '/api/design', { method: 'POST',
    headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: P, action: 'save', language: { ...(await api(`/api/design?project=${P}`)).language, rules: [{ name: 'empty' }] }, pages: [] }) });
  ok(bad.status === 400 && /the rule empty says nothing/.test((await bad.json()).error || ''), 'a rule with no text is refused by name');
  // B342: a bare string is refused rather than dropped, a color may carry
  // its alpha, every problem is reported at once, and the schema is printed.
  const cur = (await api(`/api/design?project=${P}`)).language;
  const multi = await fetch(URL.replace(/\/$/, '') + '/api/design', { method: 'POST',
    headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: P, action: 'save', language: { ...cur, scope: 'x'.repeat(130), rules: ['a bare string', ...cur.rules],
      themes: [{ ...cur.themes[0], colors: [{ name: 'glass', hex: '#1e232be0', means: 'a pane' }, { name: 'bad', hex: 'blue', means: '' }] }, ...cur.themes.slice(1)] },
      pages: [{ name: 'p', platform: 'web', frame: 'desktop', template: 'blank', blocks: [{ kind: 'card', label: 'y'.repeat(130), x: 0, y: 0, w: 2, h: 2 }] }] }) });
  const mj = await multi.json();
  ok(multi.status === 400 && Array.isArray(mj.problems) && mj.problems.length >= 4
     && mj.problems.some(x => /a rule of the language is an object with a name and a text, not 'a bare string'/.test(x))
     && mj.problems.some(x => /a color is #rrggbb or #rrggbbaa, not 'blue'/.test(x))
     && mj.problems.some(x => /what the language governs is at most 120 characters/.test(x))
     && mj.problems.some(x => /^p, block 1's label is at most 120 characters, and this is 130/.test(x))
     && !mj.problems.some(x => /1e232be0/.test(x)),
     `a save is refused with every problem at once, a bare-string rule and a hex with alpha among what it says and does not (${mj.problems?.length}: ${(mj.problems || []).join(' | ').slice(0, 160)})`);
  const alpha = await api('/api/design', { project: P, action: 'save', language: { ...cur,
      themes: [{ ...cur.themes[0], colors: [...cur.themes[0].colors, { name: 'glass', hex: '#1e232be0', means: 'a pane' }] }, ...cur.themes.slice(1)] }, pages: (await api(`/api/design?project=${P}`)).pages });
  ok(alpha.status === 200 && alpha.language.themes[0].colors.some(c => c.hex === '#1e232be0'), 'a color with alpha saves as written');
  ok(/^The record bb design save takes/.test(bb('schema')) && /at most 16 themes, 40 colors each/.test(bb('schema')) && /RULE is \{ "name"/.test(bb('schema')),
     'bb design schema prints the shape with its limits');
  const help = execFileSync('bash', [`${REPO}/scripts/bb`, 'design', 'save', '-h'], { encoding: 'utf8',
    env: { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''), BB_TOKEN: token, BB_PROJECT: P, XDG_CACHE_HOME: `${DIR}/cache-design` } });
  ok(/^bb design save FILE/.test(help) && /The record bb design save takes/.test(help), 'bb design save -h is help, not a file called -h');

  // ---- what sessions on other projects met, 29 Sep ------------------------------------------
  // Six reports and a save of this project's own. A save changed what it
  // was sent and said only that it had saved; a refusal left problems
  // out; a phone layout was kept and never said; the words carried
  // sentences no record could turn off; bb settings showed two dials of
  // seven; and a design inside every limit was too large to send.
  const post = async body => { const r = await fetch(URL.replace(/\/$/, '') + '/api/design', { method: 'POST',
    headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: P, action: 'save', ...body }) }); return { status: r.status, ...(await r.json()) }; };
  const was = await api(`/api/design?project=${P}`);
  const faulty = await post({ language: { ...was.language, corners: 'pill', rules: ['a bare rule', ...was.language.rules],
      themes: [{ name: 'A', colors: [{ name: 'bg', hex: 'blue' }, { name: 'bg', hex: '#101010' }] }] },
    pages: [{ name: 'Home', platform: 'web', frame: 'desktop', blocks: [{ kind: 'slider', x: 0, y: 0, w: 13, h: 1 },
        { kind: 'card', x: 0, y: 1, w: 4, h: 1 }, { kind: 'card', x: 0, y: 1, w: 4, h: 1 }],
      layouts: { phone: [{ x: 0, y: 0, w: 6, h: 1 }], tablet: [],
                 landscape: [{ x: 0, y: 0, w: 12, h: 1 }, { x: 0, y: 7, w: 8, h: 300 }, { x: 0, y: 2, w: 1, h: 1 }] } }] });
  const said = faulty.problems || [];
  const has = rx => said.some(x => rx.test(x));
  ok(faulty.status === 400 && said.length === 10
     && has(/a color is #rrggbb or #rrggbbaa, not 'blue'/) && has(/^A names bg twice/) && has(/corners: no such choice, 'pill'; it is one of square, soft, round, custom/)
     && has(/not 'a bare rule'/) && has(/Home, block 1's kind: no such choice, 'slider'/)
     && has(/Home, block 1 runs from column 1 to 13, and the frame has 12/) && has(/Home, blocks 2 and 3 sit in the same place/)
     && has(/Home's phone layout has 1 place for 3 blocks: one place per block/) && has(/a layout for 'tablet', which is not a frame/)
     && has(/place 2 of its landscape layout runs from row 8 to 307, and the page has 240/),
     `a record with ten things wrong is refused with all ten, the duplicate color, the frame and the layouts among them (${said.length}: ${said.join(' | ').slice(0, 200)})`);
  ok(JSON.stringify((await api(`/api/design?project=${P}`)).pages) === JSON.stringify(was.pages),
     '...and nothing of it was kept: a block is never moved to fit, a layout never dropped to save the rest');
  // A page longer than one screen, with where its blocks sit on a phone.
  const stack = Array.from({ length: 12 }, (_, i) => ({ kind: i ? 'card' : 'header', label: `part ${i + 1}`, x: 0, y: i, w: 12, h: 1 }));
  const tall = await post({ language: { ...was.language, corners: 'custom' }, pages: [...was.pages,
    { name: 'a long page', platform: 'web', frame: 'desktop', rows: 12, blocks: stack,
      layouts: { phone: stack.map((_, i) => ({ x: 0, y: i * 2, w: 6, h: 2 })) } }] });
  const made = (tall.pages || []).find(x => x.name === 'a long page') || {};
  ok(tall.status === 200 && made.rows === 12 && made.blocks[11].y === 11 && made.layouts?.phone?.[11]?.y === 22,
     `a page may be longer than its frame: twelve rows on the desktop's eight, and twenty-four on a phone (${JSON.stringify(made.layouts?.phone?.[11])})`);
  const over = await post({ language: was.language, pages: [{ name: 'too long', platform: 'web', frame: 'desktop', blocks: [stack[0], { ...stack[9] }] }] });
  ok(over.status === 400 && /too long, block 2 runs from row 10 to 10, and the page has 8: give the page more rows \(rows, up to 240\)/.test(over.error || ''),
     `...and a block past the rows a page has is refused, saying how a page is made longer (${(over.error || '').slice(0, 90)})`);
  // Two places in one spot is refused in a layout as it is among the
  // page's own blocks, and a page may run to twenty phone screens: five
  // was the limit, and a page of seven had to be drawn shorter than it is.
  const twice = await post({ language: was.language, pages: [{ name: 'twice', platform: 'web', frame: 'desktop',
    blocks: [stack[1], stack[2]], layouts: { phone: [{ x: 0, y: 0, w: 6, h: 1 }, { x: 0, y: 0, w: 6, h: 1 }] } }] });
  ok(twice.status === 400 && /twice, places 1 and 2 sit in the same place of its phone layout/.test(twice.error || ''),
     `two places in one spot are refused in a layout too (${(twice.error || '').slice(0, 80)})`);
  const seven = await post({ language: tall.language, pages: [...tall.pages, { name: 'seven screens', platform: 'web', frame: 'phone', rows: 86,
    blocks: [{ kind: 'table', label: 'the whole history', x: 0, y: 1, w: 6, h: 85 }, { kind: 'header', label: 'the top', x: 0, y: 0, w: 6, h: 1 }] }] });
  ok(seven.status === 200 && (seven.pages || []).some(x => x.name === 'seven screens' && x.rows === 86 && x.blocks[0].h === 85),
     `a page of seven phone screens is kept at its length (${seven.status} ${(seven.error || '').slice(0, 60)})`);
  ok(/system sans, custom corners, comfortable spacing, quiet motion/.test(bb()),
     `the design's one-line summary gives each choice its noun (${bb().split('\n')[0].slice(-80)})`);
  // Blocks that partly cover each other, a bad number that set off false
  // errors, a custom choice that named no rule, and a page's rules under
  // the whole of its name: the four reports of the build after.
  const partly = await post({ language: was.language, pages: [{ name: 'partly', platform: 'web', frame: 'desktop', rows: 20,
    blocks: [{ kind: 'card', label: 'a', x: 0, y: 0, w: 12, h: 3 }, { kind: 'card', label: 'b', x: 0, y: 2, w: 12, h: 3 },
             { kind: 'list', label: 'c', x: 0, y: 6, w: 12, h: 5 }, { kind: 'card', label: 'd', x: 1, y: 7, w: 4, h: 2 },
             { kind: 'overlay', label: 'e', x: 3, y: 1, w: 6, h: 6 }],
    layouts: { phone: [{ x: 0, y: 0, w: 6, h: 3 }, { x: 0, y: 2, w: 6, h: 3 }, { x: 0, y: 6, w: 6, h: 5 }, { x: 1, y: 7, w: 4, h: 2 }, { x: 0, y: 0, w: 6, h: 12 }] } }] });
  ok(partly.status === 400 && (partly.problems || []).length === 2
     && /partly, blocks 1 and 2 both cover row 3, columns 1 to 12: a block sits beside another or wholly inside it/.test(partly.error)
     && /partly, places 1 and 2 both cover row 3, columns 1 to 6 of its phone layout/.test(partly.error),
     `two blocks that partly cover each other are refused, on the page's frame and in a layout; a card inside a list and an overlay are not (${(partly.problems || []).length}: ${(partly.error || '').slice(0, 90)})`);
  const badRows = await post({ language: was.language, pages: [{ name: 'too many', platform: 'web', frame: 'desktop', rows: 241,
    blocks: [{ kind: 'header', label: 'a', x: 0, y: 0, w: 12, h: 1 }, { kind: 'card', label: 'b', x: 0, y: 12, w: 12, h: 7 }, { kind: 'card', label: 'c', x: 0, y: 19, w: 12, h: 1 }] }] });
  ok(badRows.status === 400 && (badRows.problems || []).length === 1 && /too many has 241 rows: a page on the desktop frame has 8 \(one screen\) to 240/.test(badRows.error),
     `one bad number is one message: the blocks under it are not reported as outside the page (${(badRows.problems || []).length})`);
  const gaps = { name: 'gaps', text: 'Bands are 12px by 16px.\nFields sit 8px apart.', words: ['gap'] };
  const named = await post({ language: { ...seven.language, density: 'custom', rules: [...seven.language.rules, gaps], custom: { density: 'gaps' } },
    pages: [...seven.pages, { name: 'Now: who is listening, and is it safe to restart (the default tab)', key: 'now', platform: 'web', frame: 'desktop',
      blocks: [{ kind: 'list', label: 'who', x: 0, y: 0, w: 12, h: 4 }], rules: [{ name: 'live', text: 'It polls every ten seconds.' }] }] });
  const nowPage = bb('show', 'now');
  ok(named.status === 200 && /^Space, as the rule gaps says:\n {2}Bands are 12px by 16px\.\n {2}Fields sit 8px apart\.$/m.test(nowPage)
     && /^Shape: as the design's own rules say\.$/m.test(nowPage) && /## Space\n\nAs the rule `gaps` says:\n\nBands are 12px/.test(bb('file')),
     'a custom choice that names its rule is said by that rule, in the prompt and in the file, and one that names none says so');
  ok(/now\/live/.test(bb()) && /^now\/live/m.test(bb('show', 'now/live')) && /It polls every ten seconds/.test(bb('show', 'now/live'))
     && /#### Rules of Now: who is listening[^\n]*\n\n##### now\/live/.test(bb('file')) && /Layout of Now: who is listening/.test(nowPage),
     'a page with a key of its own has its rules addressed under it, and bb design show KEY prints the page');
  const noRule = await post({ language: { ...named.language, custom: { corners: 'nowhere', motion: 'gaps' } }, pages: named.pages });
  ok(noRule.status === 400 && /custom names the rule nowhere for corners, and the language has no rule called that/.test(noRule.error)
     && /custom names a rule for motion, which is quiet and not custom/.test(noRule.error),
     `...and a custom that names a rule the language has not, or a choice that is not custom, is refused (${(noRule.error || '').slice(0, 80)})`);
  const shown2 = bb('show', 'a long page');
  ok(/on a desktop frame \(12 columns by 12 rows: the frame shows 8 of them, and the page scrolls\)/.test(shown2)
     && /The same blocks on a phone frame \(6 columns by 24 rows: the frame shows 12 of them, and the page scrolls\):/.test(shown2)
     && /Card \(a box holding one thing\): part 12, across the bottom, rows 23 to 24 of 24/.test(shown2)
     && /The same blocks on a phone frame/.test(bb('file')),
     'bb design show and the file say where the same blocks sit on every other frame the page has a layout for');
  ok(/Header \(the band at the top\): part 1/.test(shown2) && /Shape: as the design's own rules say\./.test(shown2)
     && !/monospace for data|hairlines 1px|AA contrast|one Save or Submit|each opening to detail|the top bar with/.test(shown2 + bb('file')),
     `the words say what the record says: a kind is what it is, custom hands a choice to the rules, and nothing is added that no record could turn off (${
        ((shown2 + bb('file')).match(/monospace for data|hairlines 1px|AA contrast|one Save or Submit|each opening to detail|the top bar with/) || ['none added'])[0]}, ${
        (shown2.match(/^(Shape|Type): .*$/m) || ['no Shape line'])[0].slice(0, 60)}, ${(shown2.match(/^ {2}Header .*$/m) || ['no Header line'])[0].slice(0, 60)})`);
  // Rows, in the view: a draft like the rest, and the board grows with it.
  await page.evaluate(n => { openNotebook(n, 'briefing'); openNotebook(n, 'design'); }, P);
  await page.waitForFunction(() => [...(document.querySelector('.nb #dsPagePick')?.options || [])].some(o => /^a long page/.test(o.textContent)), null, { timeout: 10000 });
  await page.selectOption(`${NB} #dsPagePick`, { label: await page.$eval(`${NB} #dsPagePick`, e => [...e.options].find(o => /^a long page/.test(o.textContent)).textContent) });
  await page.waitForSelector(`${NB} [data-dspage] [data-dsf="rows"]`, { timeout: 5000 });
  const board = () => page.$eval(`${NB} [data-dspage] .dsboard`, e => ({ rows: e.style.gridTemplateRows, tall: e.getBoundingClientRect().height / e.getBoundingClientRect().width }));
  const b12 = await board();
  ok(await page.$eval(`${NB} [data-dspage] [data-dsf="rows"]`, e => e.value === '12' && e.min === '8' && e.max === '240')
     && /repeat\(12/.test(b12.rows) && b12.tall > 0.9,
     `the view has the page's rows beside its frame, and the board is as many rows and as much taller (${b12.tall.toFixed(2)} of its width)`);
  // The two the view grew with them: a page's key beside its name, and,
  // for a choice that is custom, which rule says it.
  ok(await page.$eval(`${NB} [data-dspage] [data-dsf="key"]`, e => e.value === '' && e.maxLength === 24),
     'a page has a Key field beside its name, empty until somebody gives it one');
  if (!(await page.$eval(`${NB} [data-sect="design:language"]`, d => d.open))) await openFold(page, `${NB} [data-sect="design:language"]`);
  ok(await page.$eval(`${NB} #dsCustom-density`, e => e.value === 'gaps' && [...e.options].some(o => o.textContent === 'no rule named'))
     && await page.$eval(`${NB} #dsCustom-corners`, e => e.value === '') && !(await page.$(`${NB} #dsCustom-motion`)),
     'a choice that is custom has a pulldown of the rules beside it, on the rule it names, and one that is not has none');
  await page.fill(`${NB} [data-dspage] [data-dsf="rows"]`, '16');
  await page.dispatchEvent(`${NB} [data-dspage] [data-dsf="rows"]`, 'change');
  await page.waitForFunction(() => /repeat\(16/.test(document.querySelector('.nb [data-dspage] .dsboard')?.style.gridTemplateRows || ''), null, { timeout: 5000 });
  ok((await api(`/api/design?project=${P}`)).pages.find(x => x.name === 'a long page').rows === 12
     && await page.$eval(`${NB} #roadmapSaveQuiet`, b => !b.disabled),
     '...a change to them is a draft until Save');
  await page.click(`${NB} #roadmapRevert`);
  await page.waitForFunction(() => document.querySelector('.nb #roadmapSaveQuiet')?.disabled, null, { timeout: 10000 });
  // A design inside every one of its limits is one the server takes.
  const big = await post({ language: { ...was.language, rules: Array.from({ length: 30 }, (_, i) => ({ name: `long-${i}`, text: 'x'.repeat(19000), words: ['w'] })) }, pages: was.pages });
  ok(big.status === 200 && (big.language?.rules || []).length === 30,
     `a design of half a megabyte saves: the design is the one body here that is a document (${big.status} ${(big.error || '').slice(0, 60)})`);
  ok((await post({ language: was.language, pages: was.pages })).status === 200, '...and the record is put back');
  await page.evaluate(n => { openNotebook(n, 'briefing'); openNotebook(n, 'design'); }, P);
  await page.waitForFunction(() => ![...(document.querySelector('.nb #dsPagePick')?.options || [])].some(o => /^a long page/.test(o.textContent))
    && document.querySelector('.nb #dsPagePick')?.options.length > 0, null, { timeout: 10000 });
  await page.selectOption(`${NB} #dsPagePick`, 'p1');
  await page.waitForSelector(`${NB} [data-dspage="p1"]`, { timeout: 5000 });
  const dials = execFileSync('bash', [`${REPO}/scripts/bb`, 'settings'], { encoding: 'utf8',
    env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: P }, cwd: `${DIR}/ws/${P}` });
  ok(['Add to roadmap', 'File bugs', 'Add rules', 'Fill in build and test', 'Add to the design', 'Run its container', 'Report BuilderBot bugs']
       .every(d => new RegExp(`Claude may: ${d}\\s+(auto|ask|deny)`).test(dials)),
     `bb settings lists every dial as it stands, Add to the design among them (${(dials.match(/Claude may: [^\n]+/g) || []).length} of 7)`);

  // ---- a theme's own rules and a page's own: a Rules section inside each ------------------
  // The Nostromo scheme has needs no other theme shares (the operator, 28
  // Sep): a rules section inside the theme and inside the page, the
  // Briefing's list again, following the pulldown; a rule there reaches a
  // session as HOLDER/RULE, and bb design show reads it so.
  await page.selectOption(`${NB} #dsThemePick`, '0');
  await page.waitForSelector(`${NB} [data-dstheme="0"] [data-dsrules="t0"]`, { timeout: 5000 });
  ok(await page.$eval(`${NB} [data-dstheme="0"] [data-sect="design:rules:t0"] > summary .t`, e => e.textContent) === "Rules"
     && await page.$eval(`${NB} [data-dstheme="0"] [data-sect="design:rules:t0"] > summary .sst`, e => e.textContent) === 'none'
     && /What holds for Night alone/.test(await page.$eval(`${NB} [data-sect="design:rules:t0"] .hint`, e => e.textContent))
     && await page.$eval(`${NB} [data-dstheme="0"]`, e => e.querySelector('[data-sect="design:rules:t0"]').compareDocumentPosition(e.querySelector('.dscolors')) & Node.DOCUMENT_POSITION_FOLLOWING),
     "the theme shown carries a Rules section inside it, above its colors, counting none");
  if (!(await page.$eval(`${NB} [data-sect="design:rules:t0"]`, d => d.open))) await openFold(page, `${NB} [data-sect="design:rules:t0"]`);
  await page.click(`${NB} [data-dstheme="0"] [data-sect="design:rules:t0"] [data-dsruleadd]`);
  await page.waitForSelector(`${NB} [data-dsrules="t0"] .rulerow[data-i="0"].editing .rlName`, { timeout: 5000 });
  await page.fill(`${NB} [data-dsrules="t0"] .rulerow[data-i="0"] .rlName`, 'Hull');
  await page.fill(`${NB} [data-dsrules="t0"] .rulerow[data-i="0"] .rlWords`, 'texture, hull');
  await page.fill(`${NB} [data-dsrules="t0"] .rulerow[data-i="0"] .rlText`, 'Night alone carries drawn textures behind the page.');
  await page.selectOption(`${NB} #dsThemePick`, '1');
  await page.waitForSelector(`${NB} [data-dstheme="1"] [data-dsrules="t1"]`, { timeout: 5000 });
  ok(!(await page.$(`${NB} [data-dsrules="t0"]`)) && /What holds for Day alone/.test(await page.$eval(`${NB} [data-sect="design:rules:t1"] .hint`, e => e.textContent)),
     "the theme's Rules section follows the pulldown: Day's, with none, once Day is chosen");
  await page.selectOption(`${NB} #dsThemePick`, '0');
  await page.waitForSelector(`${NB} [data-dsrules="t0"] .rulerow[data-i="0"]`, { timeout: 5000 });
  ok(await page.$eval(`${NB} [data-dsrules="t0"] .rulerow[data-i="0"] .btitle`, e => e.textContent) === 'Hull', "...and back to Night's, with the rule typed there");
  if (!(await page.$eval(`${NB} [data-sect="design:rules:p1"]`, d => d.open))) await openFold(page, `${NB} [data-sect="design:rules:p1"]`);
  await page.click(`${NB} [data-dspage="p1"] [data-sect="design:rules:p1"] [data-dsruleadd]`);
  await page.waitForSelector(`${NB} [data-dsrules="p1"] .rulerow[data-i="0"].editing .rlName`, { timeout: 5000 });
  await page.fill(`${NB} [data-dsrules="p1"] .rulerow[data-i="0"] .rlName`, 'first read');
  await page.fill(`${NB} [data-dsrules="p1"] .rulerow[data-i="0"] .rlText`, 'The chart is read before anything else on this page.');
  await saved();
  const own = await api(`/api/design?project=${P}`);
  ok(own.language.themes[0].rules?.[0]?.name === 'hull' && own.language.themes[0].rules[0].words.join() === 'texture,hull'
     && own.pages[0].rules?.[0]?.name === 'first-read' && own.pages[0].rules[0].paths.length === 0,
     `a rule typed under a theme saves with the theme, and one under a page with the page (${JSON.stringify(own.language.themes[0].rules)})`);
  const eff2 = JSON.parse(execFileSync('bash', [`${REPO}/scripts/bb`, 'rules', '--json'], { encoding: 'utf8',
    env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: P } }));
  ok(eff2.some(r => r.name === 'night/hull' && r.design && /^For the Night theme\. Night alone/.test(r.text))
     && eff2.some(r => r.name === 'the-home-dashboard/first-read' && /^For the home dashboard\. The chart/.test(r.text)),
     'both reach a session as rules named under their holder, the text saying whose they are');
  ok(/^night\/hull \(for the Night theme\) \(applies to: texture, hull\)\n\nNight alone carries/.test(bb('show', 'night/hull')),
     `bb design show THEME/RULE prints the theme's rule (${bb('show', 'night/hull').split('\n')[0]})`);
  const themeOut = bb('show', 'Night');
  ok(/^Night \(dark\), one theme of 2:\n  bg #/.test(themeOut) && /night\/hull \(applies to: texture, hull\)\nNight alone carries/.test(themeOut),
     'bb design show THEME prints the theme: its colors and its own rules');
  const pre2 = await api(`/api/preamble?project=${P}`);
  ok(/  night\/hull: texture, hull \(the design's: bb design show reads it/.test(pre2.text)
     && /This project's notebook holds a design already: 2 themes \(Night, Day\); 1 page: the home dashboard; 3 design rules and 2 of a theme's or a page's own\./.test(pre2.text)
     && /Read `bb design show` before laying out or styling anything/.test(pre2.text),
     "the briefing names the theme's rule under it, and says the notebook holds a design, what is in it, and to read it before building");
  const file2 = bb('file');
  ok(/#### Rules of Night's own\n\n##### night\/hull\n\nApplies to: texture, hull\n\nNight alone carries/.test(file2)
     && /##### the-home-dashboard\/first-read\n\nThe chart is read/.test(file2),
     "the file carries a theme's rules under the theme and a page's under the page");
  const pagePrompt = bb('show', '1');
  ok(/This page's own rules:\n  the-home-dashboard\/first-read: The chart is read before/.test(pagePrompt) && /    Night's own rules:\n      night\/hull: texture, hull \(`bb design show night\/hull` reads it\)/.test(pagePrompt),
     "bb design show PAGE carries the page's own rules whole and names the theme's under the theme");
  await page.selectOption(`${NB} #dsThemePick`, '0');
  await page.waitForSelector(`${NB} [data-dsrules="t0"] .rulerow[data-i="0"]`, { timeout: 5000 });
  for (const key of ['t0', 'p1']){
    if (!(await page.$eval(`${NB} [data-sect="design:rules:${key}"]`, d => d.open))) await openFold(page, `${NB} [data-sect="design:rules:${key}"]`);
    if (!(await page.$eval(`${NB} [data-dsrules="${key}"] .rulerow[data-i="0"]`, d => d.open))) await page.click(`${NB} [data-dsrules="${key}"] .rulerow[data-i="0"] summary`);
    await page.waitForFunction(k => { const d = document.querySelector(`.nb [data-dsrules="${k}"] .rulerow[data-i="0"]`); return d?.open && !d.getAnimations({subtree: true}).length; }, key, { timeout: 10000 });
    await page.click(`${NB} [data-dsrules="${key}"] .rulerow[data-i="0"] .rlRm`);
    await page.waitForFunction(k => !document.querySelector(`.nb [data-dsrules="${k}"] .rulerow`), key, { timeout: 5000 });
  }
  await saved();
  const gone2 = await api(`/api/design?project=${P}`);
  ok(gone2.language.themes[0].rules.length === 0 && gone2.pages[0].rules.length === 0, 'Remove rule under a theme or a page takes it out');
}

// ---- the dial: Claude may: Add to the design -------------------------------------------
// A session's save goes through the project's setting: auto lands it (as
// above), ask holds it for the operator's approval, deny refuses it by name.
{
  const gate = mode => api('/api/prefs', { project: P, gate: { design: mode } });
  const rec = JSON.parse(bb('json'));
  rec.pages[0].notes = 'saved under ask';
  const tmp = `${DIR}/design-ask.json`;
  writeFileSync(tmp, JSON.stringify(rec));
  await gate('deny');
  let refused = '';
  try { bb('save', tmp); } catch (e) { refused = String(e.stderr); }
  ok(/Claude may: Add to the design is deny/.test(refused), `under deny a session's save is refused naming the setting (${refused.trim().slice(0, 80)})`);
  await gate('ask');
  const held = bb('save', tmp);
  const queue = await api(`/api/pending?project=${P}`);
  const mine = (queue.rows || queue.pending || queue.items || []).find(r => r.kind === 'design');
  ok(/held for the operator's approval/.test(held) && mine && /theme/.test(mine.summary) && (await api(`/api/design?project=${P}`)).pages[0].notes !== 'saved under ask',
     `under ask the save waits on the notebook with a summary and nothing has landed (${(mine || {}).summary})`);
  const ok2 = await api('/api/pending', { project: P, action: 'approve', ids: [mine.id] });
  ok(!ok2.error && (await api(`/api/design?project=${P}`)).pages[0].notes === 'saved under ask',
     `...and Approve lands it as the session's save (${ok2.error || 'ok'})`);
  await gate('auto');
}

// ---- a page removed, and the record put back ------------------------------------------
await page.click(`${NB} [data-dspage] [data-dspagerm]`);
await page.waitForFunction(() => !document.querySelector('.nb [data-dspage]'), null, { timeout: 5000 });
await page.selectOption(`${NB} #dsThemePick`, '0');
await page.waitForSelector(`${NB} [data-dstheme="0"]`, { timeout: 5000 });
await page.selectOption(`${NB} [data-dstheme="0"] [data-dst="from"]`, 'default');
await page.waitForFunction(() => document.querySelector('.nb #dst-0-hex-0')?.value === '#1a1f26', null, { timeout: 5000 });
await page.selectOption(`${NB} #dsThemePick`, '1');
await page.waitForSelector(`${NB} [data-dstheme="1"]`, { timeout: 5000 });
await page.click(`${NB} [data-dstheme="1"] [data-dstrm]`);
await page.waitForFunction(() => document.querySelector('.nb #dsThemePick')?.options.length === 1, null, { timeout: 5000 });
await saved();
const gone = await api(`/api/design?project=${P}`);
ok(gone.pages.length === 0 && gone.language.themes.length === 1 && gone.language.themes[0].colors[0].hex === '#1a1f26',
   'Remove page and Save take the page out, and the language goes back to one theme filled from Default');
rmSync(`${DIR}/ws/${P}/docs`, { recursive: true, force: true });
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
