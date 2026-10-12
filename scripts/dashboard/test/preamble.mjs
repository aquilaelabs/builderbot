// What a session is handed, and the one place that decides it.
//
// The house rules, the open roadmap and the open bugs are joined into the
// string bb-tty gives `claude` as --append-system-prompt. That assembly used
// to be shell inside the launcher, where it was fine while the launcher was
// its only reader, and stopped being fine the moment the Briefing tab wanted
// to show a person what their sessions are sent. Two assemblies of one string
// drift, and the one that drifts is the one nobody runs.
//
// So what is measured here is the assembly itself (order, joins, the cap) and
// then the thing that makes it worth having: the tab renders the SAME string
// the endpoint returns, byte for byte, rather than its own idea of it.
import { URL, DIR, launch, newPage, ok, done, ready, sleep, patience } from './lib.mjs';
import { writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';

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
put('roadmap.json', { projects: {}, unsaved: {} });
put('bugs.json', { projects: {} });
let p = await pre();
ok((p.parts || []).map(x => x.name).join(',') === 'core,rules,briefing,live'
   && /this node carries git, tmux, jq, python3 and curl by itself/.test(p.text)
   && /\(global\)/.test(p.text) && (p.notes || []).length === 0,
   `a project with nothing set still gets the briefing and the shipped global rules (${
     (p.parts || []).map(x => x.name).join(',') || 'none'}, ${p.bytes} bytes)`);
// The line between the two: the briefing states what is true of the machine,
// a shipped rule is an obligation, and nothing is said in both. An obligation
// that was in the briefing too could not be turned off by its switch.
// What a change asked for during a test run does is the project's setting,
// said in the briefing in the words the session acts on (25 Sep): waits by
// default, and the other way once the settings say so.
ok(/a new ask never cuts in\. Finish the ask in hand, run the tests, fix what failed and run them again until they pass/.test(p.text)
   && !/end that run by the pid/.test(p.text),
   'the briefing says a new ask waits for the ask in hand to be finished and tested, the default');
const setChange = mode => page.evaluate(async m => (await (await fetch('/api/prefs', { method: 'POST',
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project: 'alpha', test_change: m }) })).json()), mode);
await setChange('restart');
ok(/cuts into whatever test run is going, a suite run in the middle of the work or the gate at its end.*end that run by the pid you started it with.*still yours to fix before the run that lands/s.test((await pre()).text),
   '...and, set the other way, that any run is cut for the new ask and what it had found is still fixed');
// The asker's own reply style rides the block (a per-account setting on
// the project, 25 Sep), and the project's briefing style drops the filler
// words of every part but the live line: fewer bytes, code and names kept.
const setPref = body => page.evaluate(async b => (await (await fetch('/api/prefs', { method: 'POST',
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project: 'alpha', ...b }) })).json()), body);
ok(!/Replies to the person/.test(p.text), 'nothing is said about replies until the person sets it');
await setPref({ reply: 'minimal' });
const withReply = await pre();
ok(/## Replies\n\nReplies to the person: minimal/.test(withReply.text) && (withReply.parts || []).some(x => x.name === 'replies'),
   'set to minimal, the block says so in its own part');
await setPref({ reply: '', asks: 'rarely' });
const asked = await pre();
ok(/## Replies\n\nQuestions to the person: rarely/.test(asked.text) && !/Replies to the person/.test(asked.text),
   'how often to ask is the person\'s own pick too, said in the same part, on its own when replies are default');
await setPref({ asks: 'more' });
const more = await pre();
ok(/Questions to the person: more/.test(more.text) && /before a judgment call/.test(more.text),
   '...and more, for a person who wants the judgment calls put to them (the operator, 25 Sep)');
await setPref({ asks: '' });
await setChange('wait');
// Answering while a run goes is the briefing's (While tests run): what nobody
// would switch off is not a global rule (the operator, 2 Oct), so it is said
// there once and nowhere else.
ok(p.text.split('answer while it runs').length === 2 && !/never holds a reply/.test(p.text)
   && p.text.split('unshelve N WHY').length <= 2,
   'an obligation reaches a session once, from the briefing and not again as a rule; the shelf is said by the roadmap\'s own note');

// ---- the order, which is the operator's rules first -------------------------
// How they want this worked on comes before what there is to work on. Asserted
// by position rather than presence: all three are one string and any of them
// would be "in" it.
put('rules.json', { projects: { alpha: { rules: [
  { name: 'only-rule', text: 'RULESMARK the standing rule', by: 'you' }] } } });
put('bugs.json', { projects: { alpha: [
  { id: 1, title: 'BUGMARK something is wrong', severity: 'high',
    status: 'open', at: 1750000000, by: 'you' }] } });
const roadmapFile = read('roadmap.json');
roadmapFile.projects = { alpha: [{ id: 1, text: 'ROADMAPMARK a thing to do', by: 'you' }] };
put('roadmap.json', roadmapFile);

p = await pre();
const at = s => p.text.indexOf(s);
ok(at('RULESMARK') >= 0 && at('ROADMAPMARK') >= 0 && at('BUGMARK') >= 0,
   'the rules, the roadmap and the bugs are all in the block');
ok(at('RULESMARK') < at('ROADMAPMARK') && at('ROADMAPMARK') < at('BUGMARK'),
   '...in that order: how to work on it, then what there is, then what is broken');
ok(!/\n\n\n/.test(p.text),
   '...joined by one blank line, so a store with nothing leaves no gap where it would have been');
ok(p.bytes === Buffer.byteLength(p.text, 'utf8') && (p.notes || []).length === 0,
   `...and the size is the block's own (${p.bytes} bytes)`);
ok((p.parts || []).map(x => x.name).join(',') === 'core,rules,briefing,live,roadmap,bugs',
   `...with each named and measured separately, the briefing's core and the rules first (${
     (p.parts || []).map(x => `${x.name} ${x.bytes}`).join(' · ')})`);

// ---- a store that contributes nothing leaves no gap -------------------------
put('bugs.json', { projects: {} });
p = await pre();
ok(at('RULESMARK') >= 0 && !/BUGMARK/.test(p.text) && !/\n\n\n/.test(p.text)
   && (p.parts || []).map(x => x.name).join(',') === 'core,rules,briefing,live,roadmap',
   'a tracker with nothing open drops out of the block entirely, gap included');

// ---- a share for each part, and no tail to lose ------------------------------
// A project only grows (the operator, 29 Sep). The block used to be cut at
// its end past a fixed size, so the bugs went first and then the roadmap's
// last items, blind to what they were, and the notebook refused a 31st
// item to keep it short. Now what is kept and what is sent are two things:
// each part that grows has a share, one over it says less per row before it
// leaves a row out, and every part is always there.
const SHARE = { rules: 16384, roadmap: 8192, bugs: 6144 };
const part = name => (p.parts || []).find(x => x.name === name) || {};
{
  const steps = [{ text: 'the first step, which is done', done: true }, { text: 'the second step, to do' }];
  const big = read('roadmap.json');
  big.projects = { alpha: [{ id: 1, by: 'you', text: 'ROADMAPMARK a plan half done', steps },
                           { id: 2, by: 'you', text: 'PARKEDMARK a parked one', shelved: 1790000000 }] };
  put('roadmap.json', big);
  p = await pre();
  ok(/1 of 2 steps done; still open:\n {4}2\. the second step, to do/.test(p.text) && !/the first step, which is done/.test(p.text),
     'a step that is done is counted and not printed, and an open one keeps its own number');
  ok(part('roadmap').share === SHARE.roadmap && part('rules').share === SHARE.rules
     && part('briefing').share === undefined && !part('roadmap').left,
     `each part that grows carries its share, and one inside it leaves nothing out (${
       (p.parts || []).map(x => `${x.name} ${x.bytes}${x.share ? ' of ' + x.share : ''}`).join(' · ')})`);

  // Sixty items with steps: over the share with everything said, inside it
  // as titles, so the steps are what goes and every item is still named.
  const mid = [];
  for (let i = 0; i < 60; i++)
    mid.push({ id: i + 1, by: 'you', text: `MIDITEM ${i} with enough words on it to be a real line of about fifty bytes`,
               steps: [{ text: 'a step of some length that says what has to be true' }, { text: 'and another one of the same kind' },
                       { text: 'and a third so that the steps are the long half' }, { text: 'and a fourth' }, { text: 'and a fifth of them' }] });
  big.projects = { alpha: mid.concat([{ id: 900, by: 'you', text: 'PARKEDMARK a parked one', shelved: 1790000000 }]) };
  put('roadmap.json', big);
  p = await pre();
  ok(part('roadmap').bytes <= SHARE.roadmap && part('roadmap').left === 'the steps of its items'
     && (p.text.match(/- R\d+ {2}MIDITEM/g) || []).length === 60 && /MIDITEM 59[^\n]*\(5 of 5 steps open\)/.test(p.text)
     && /PARKEDMARK/.test(p.text) && !/a step of some length/.test(p.text),
     `a list over its share says less per item first: every title, the steps as a count (${part('roadmap').bytes} bytes)`);
  ok(/The list is longer than its share of your prompt, so this leaves out the steps of its items: `bb roadmap` prints all of it/.test(p.text)
     && (p.notes || []).length === 1 && /the roadmap part is over its share/.test(p.notes[0]),
     '...saying so in the text, where the session reading it will see it, and in a note for whoever opened the terminal');

  // Three thousand items and four hundred bugs: what fits, in the
  // operator's own order, and the rest as a count. The bugs are after the
  // roadmap and all of them used to be lost to it.
  const many = [];
  for (let i = 0; i < 3000; i++)
    many.push({ id: i + 1, by: 'you', text: `item ${i} with enough words on it to be a real line of about fifty bytes` });
  big.projects = { alpha: many };
  put('roadmap.json', big);
  const bugsFile = read('bugs.json');
  const was = JSON.stringify(bugsFile);
  bugsFile.projects = { alpha: Array.from({ length: 400 }, (_, i) => ({ id: i + 1, status: 'open',
    severity: i === 7 ? 'high' : i % 2 ? 'medium' : 'low',
    title: i === 7 ? 'BUGMARK the one that matters most' : `bug ${i} with a title of a usual length, which says what is wrong and where` })) };
  put('bugs.json', bugsFile);
  p = await pre();
  const kept = (p.text.match(/^- R\d+ {2}item /gm) || []).length;
  ok(part('roadmap').bytes <= SHARE.roadmap && kept > 50 && kept < 3000 && /- R1 {2}item 0 /.test(p.text)
     && new RegExp(`\\nand ${3000 - kept} more open\\.`).test(p.text)
     && new RegExp(`leaves out ${3000 - kept} of its 3000 open items`).test(p.text),
     `a list far over its share fills what room there is from the top and counts the rest (${kept} of 3000 in ${part('roadmap').bytes} bytes)`);
  const bugsKept = (p.text.match(/^- B\d+ \[/gm) || []).length;
  ok(part('bugs').share === SHARE.bugs && part('bugs').bytes <= SHARE.bugs && bugsKept > 20 && bugsKept < 400
     && p.text.indexOf('BUGMARK the one that matters most') > 0
     && p.text.indexOf('BUGMARK') < p.text.indexOf('- B', p.text.indexOf('BUGMARK') + 10)
     && /\nand \d+ more \(\d+ medium, \d+ low\)\./.test(p.text) && /`bb bug` lists every one/.test(p.text),
     `...and the bugs are all still there in their own share, the worst first, the rest counted by severity (${bugsKept} of 400)`);
  ok(p.bytes === Buffer.byteLength(p.text, 'utf8') && p.bytes < 70000 && /next session looks first\.$/.test(p.text)
     && (p.notes || []).length === 2,
     `the block ends on its own last words and not on a cut (${p.bytes} bytes)`);
  put('bugs.json', JSON.parse(was));
}

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
put('roadmap.json', { projects: {}, unsaved: {} });
put('bugs.json', { projects: {} });

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
// ---- the briefing has to be where the IMAGE puts it -------------------------
// The suite runs server.py from the checkout, so a path that is only right in a
// checkout passes every test here and still ships a controller whose sessions
// get no briefing at all. That is exactly what happened: the Dockerfile copies
// config/templates/ to /opt/builderbot/templates/ and the first version of
// preamble.py looked in /opt/builderbot/config/templates/. This asserts the two
// agree by reading the Dockerfile, rather than trusting either.
{
  const root = join(import.meta.dirname, '..', '..', '..');
  const dockerfile = readFileSync(join(root, 'Dockerfile'), 'utf8');
  const py = readFileSync(join(root, 'scripts', 'dashboard', 'preamble.py'), 'utf8');
  const copy = (dockerfile.match(/^COPY config\/templates\/ (\S+)/m) || [])[1] || '';
  const dest = copy.replace(/\/$/, '') + '/briefing.md';
  ok(!!copy && py.includes(`Path("${dest}")`),
     `preamble.py looks for the briefing where the image puts it (${dest})`);
  ok(existsSync(join(root, 'config', 'templates', 'briefing.md')),
     '...and the file it ships is in the tree');
}

// ---- bb status tells a refusal from a silence (R62) --------------------------
// The first version reported an expired token as "the controller did not
// answer", which is the mistake bbapi.request exists to prevent and that
// bb-gate had already made once. A session sent chasing a network problem
// when the answer is "open this session's tab" is the cost.
{
  const root = join(import.meta.dirname, '..', '..', '..');
  const run = (env) => {
    try {
      return execFileSync('bash', [join(root, 'scripts', 'bb'), 'status'],
        { encoding: 'utf8', cwd: root, env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (e) { return `${e.stdout || ''}${e.stderr || ''}` || `THREW ${e}`; }
  };
  const line = out => (out.split('\n').find(l => /^\s*controller /.test(l)) || out.split('\n').slice(0, 2).join(' | ')).trim();
  const refused = line(run({ BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''),
                             BB_TOKEN: 'bbs_nonsense', BB_PROJECT: 'alpha' }));
  ok(/refused this session/.test(refused) && !/did not answer/.test(refused),
     `a credential the controller rejects reads as a refusal, not as silence (${refused})`);
  const away = line(run({ BUILDERBOT_ROLE: 'node', BB_CONTROLLER: 'https://127.0.0.1:59999',
                          BB_TOKEN: 'bbs_nonsense', BB_PROJECT: 'alpha' }));
  ok(/did not answer/.test(away),
     `...and a controller that is really not there reads as silence (${away})`);
}

await done(browser);
