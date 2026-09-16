// What a session is handed, and the one place that decides it.
//
// The house rules, the open roadmap and the open bugs are joined into the
// string bb-tty gives `claude` as --append-system-prompt. That assembly used
// to be shell inside the launcher, where it was fine while the launcher was
// its only reader — and stopped being fine the moment the Briefing tab wanted
// to show a person what their sessions are sent. Two assemblies of one string
// drift, and the one that drifts is the one nobody runs.
//
// So what is measured here is the assembly itself (order, joins, the cap) and
// then the thing that makes it worth having: the tab renders the SAME string
// the endpoint returns, byte for byte, rather than its own idea of it.
import { URL, DIR, launch, newPage, ok, done, ready, sleep, patience } from './lib.mjs';
import { writeFileSync, readFileSync, existsSync } from 'node:fs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

const api = (p) => page.evaluate(async u => {
  const r = await fetch(u); return r.json();
}, p);
const pre = () => api('/api/preamble?project=' + encodeURIComponent('alpha'));

// Written straight to the state files: this is about the joining, not about
// how a rule or an item gets filed.
const put = (name, obj) => writeFileSync(`${DIR}/state/${name}`, JSON.stringify(obj));
const read = (name) => {
  try { return JSON.parse(readFileSync(`${DIR}/state/${name}`, 'utf8')); }
  catch { return {}; }
};

// ---- nothing at all --------------------------------------------------------
// A project with no rules, no open items and no open bugs still gets the
// briefing: how this machine works is true of every project, and it is the
// thing a new project's first session most needs (R63). What it does NOT get
// is an empty rules, roadmap or bugs piece.
put('rules.json', { projects: {} });
put('todos.json', { projects: {}, unsaved: {} });
put('bugs.json', { projects: {} });
let p = await pre();
ok((p.parts || []).map(x => x.name).join(',') === 'briefing'
   && /Stay in this project/.test(p.text) && p.capped === false,
   `a project with nothing set still gets the briefing and nothing else (${
     (p.parts || []).map(x => x.name).join(',') || 'none'}, ${p.bytes} bytes)`);

// ---- the order, which is the operator's rules first -------------------------
// How they want this worked on comes before what there is to work on. Asserted
// by position rather than presence: all three are one string and any of them
// would be "in" it.
put('rules.json', { projects: { alpha: { rules: [
  { name: 'only-rule', text: 'RULESMARK the standing rule', by: 'you' }] } } });
put('bugs.json', { projects: { alpha: [
  { id: 1, title: 'BUGMARK something is wrong', severity: 'high',
    status: 'open', at: 1750000000, by: 'you' }] } });
const todos = read('todos.json');
todos.projects = { alpha: [{ id: 1, text: 'TODOMARK a thing to do', by: 'you' }] };
put('todos.json', todos);

p = await pre();
const at = s => p.text.indexOf(s);
ok(at('RULESMARK') >= 0 && at('TODOMARK') >= 0 && at('BUGMARK') >= 0,
   'the rules, the roadmap and the bugs are all in the block');
ok(at('RULESMARK') < at('TODOMARK') && at('TODOMARK') < at('BUGMARK'),
   '...in that order: how to work on it, then what there is, then what is broken');
ok(!/\n\n\n/.test(p.text),
   '...joined by one blank line, so a store with nothing leaves no gap where it would have been');
ok(p.bytes === Buffer.byteLength(p.text, 'utf8') && p.capped === false,
   `...and the size is the block's own (${p.bytes} bytes)`);
ok((p.parts || []).map(x => x.name).join(',') === 'briefing,rules,roadmap,bugs',
   `...with each named and measured separately, the briefing first (${
     (p.parts || []).map(x => `${x.name} ${x.bytes}`).join(' · ')})`);

// ---- a store that contributes nothing leaves no gap -------------------------
put('bugs.json', { projects: {} });
p = await pre();
ok(at('RULESMARK') >= 0 && !/BUGMARK/.test(p.text) && !/\n\n\n/.test(p.text)
   && (p.parts || []).map(x => x.name).join(',') === 'briefing,rules,roadmap',
   'a tracker with nothing open drops out of the block entirely, gap included');

// ---- the cap ---------------------------------------------------------------
// One argument cannot pass the kernel's MAX_ARG_STRLEN, and past it exec
// answers "Argument list too long" and the pane dies without saying why. The
// cut lands on a line boundary and says so IN the text, so a session reading
// it knows it has part of a list rather than all of one.
const many = [];
for (let i = 0; i < 3000; i++)
  many.push({ id: i + 1, by: 'you',
              text: `item ${i} with enough words on it to be a real line of about fifty bytes` });
const big = read('todos.json');
big.projects = { alpha: many };
put('todos.json', big);
p = await pre();
ok(p.capped === true && p.bytes > p.max,
   `a list past the limit is reported as cut, with its real size (${p.bytes} of ${p.max})`);
ok(Buffer.byteLength(p.text, 'utf8') <= p.max + 200,
   `...and what a session gets is the limit, not the list (${Buffer.byteLength(p.text, 'utf8')} bytes)`);
ok(/did not fit in the prompt/.test(p.text),
   '...saying so in the text, where the session reading it will see it');
ok(/\n\[the rest/.test(p.text),
   '...after a line boundary, so the cut never lands mid-item');

// ---- and the tab shows exactly that ----------------------------------------
// The whole point. A section that renders its own join would be a section that
// quietly stops describing what sessions get, which is the failure this module
// exists to make impossible.
await page.evaluate(() => setView('terminal'));
await page.evaluate(() => openNotebook('alpha', 'briefing'));
await page.waitForSelector('.nb [data-view="briefing"]:not([hidden])', { timeout: 20000 });
// Attached, not visible: the section is shut by default, which is the point
// of the last assertion in this block.
await page.waitForSelector('#preText', { state: 'attached', timeout: 20000 });
const shown = await page.$eval('#preText', el => el.value);
const live = await pre();
ok(shown === live.text,
   `the Briefing section holds the string the endpoint returns, byte for byte (${
     shown.length} vs ${live.text.length})`);
ok(await page.$eval('#preText', el => el.readOnly),
   '...read-only: it is what a session is sent, not somewhere to write');
const head = await page.$eval('[data-sect="briefing:preamble"] summary',
                              el => el.textContent.replace(/\s+/g, ' ').trim());
ok(/What a session is sent/.test(head) && /KB|bytes/.test(head),
   `...under a heading that says what it is and how big (${head})`);
ok(await page.$eval('[data-sect="briefing:preamble"]', el => !el.open),
   '...shut by default: it is a thing to check, not a thing to read every time');

// Put the fixture back for whatever runs next.
put('rules.json', { projects: {} });
put('todos.json', { projects: {}, unsaved: {} });
put('bugs.json', { projects: {} });

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
