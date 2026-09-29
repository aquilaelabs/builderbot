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
ok((p.parts || []).map(x => x.name).join(',') === 'briefing,live,rules'
   && /this node carries git, tmux, jq, python3 and curl by itself/.test(p.text)
   && /\(global\)/.test(p.text) && p.capped === false,
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
ok(/may cut into the final test run only.*end that run by the pid you started it with.*Work still in progress on the ask in hand.*finishes first/s.test((await pre()).text),
   '...and, set the other way, that only the final run is interrupted and work in hand finishes first');
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
ok(p.text.split('never holds a reply').length === 2 && p.text.split('unshelve N WHY').length <= 2,
   'an obligation reaches a session once, as a rule, and not again from the briefing; the shelf is said by the roadmap\'s own note');

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
ok(p.bytes === Buffer.byteLength(p.text, 'utf8') && p.capped === false,
   `...and the size is the block's own (${p.bytes} bytes)`);
ok((p.parts || []).map(x => x.name).join(',') === 'briefing,live,rules,roadmap,bugs',
   `...with each named and measured separately, the briefing first (${
     (p.parts || []).map(x => `${x.name} ${x.bytes}`).join(' · ')})`);

// ---- a store that contributes nothing leaves no gap -------------------------
put('bugs.json', { projects: {} });
p = await pre();
ok(at('RULESMARK') >= 0 && !/BUGMARK/.test(p.text) && !/\n\n\n/.test(p.text)
   && (p.parts || []).map(x => x.name).join(',') === 'briefing,live,rules,roadmap',
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
const big = read('roadmap.json');
big.projects = { alpha: many };
put('roadmap.json', big);
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
