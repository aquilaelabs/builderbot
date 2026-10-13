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
   && /## What holds every time/.test(p.text) && /\(global\)/.test(p.text) && (p.notes || []).length === 0,
   `a project with nothing set still gets the briefing's core and the shipped global rules (${
     (p.parts || []).map(x => x.name).join(',') || 'none'}, ${p.bytes} bytes)`);
// The rest of the briefing is topics (R202): the block carries the index
// and bb help TOPIC the text, so a session pays for the manual only where
// the work reaches it. A topic the tree gates out (Android, here) is not
// in the index and still answers when asked for.
const slugs = (p.topics || []).map(t => t.slug);
ok(/Topics of this briefing, each read with `bb help TOPIC`/.test(p.text) && /- build: bb build, bb test and bb run/.test(p.text)
   && !/this node carries git, tmux, jq, python3 and curl by itself/.test(p.text)
   && slugs.includes('build') && slugs.includes('capture') && !slugs.includes('android')
   && p.bytes < 20000,
   `the block carries the index of topics and not their text, the tree's gates leaving one out (${slugs.join(' ')}; ${p.bytes} bytes)`);
const build = await api('/api/preamble?project=alpha&topic=build');
const droid = await api('/api/preamble?project=alpha&topic=android');
ok(/^## Building and testing/.test(build.text || '') && /this node carries git, tmux, jq, python3 and curl by itself/.test(build.text || '')
   && /^## Android/.test(droid.text || '')
   && (await fetch(URL.replace(/\/$/, '') + '/api/preamble?project=alpha&topic=nope',
        { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).status === 404,
   'a topic is its section whole, a gated one answers when asked for, and an unknown name is refused');
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

// ---- the order, and the lists as counts (R202) ------------------------------
// How they want this worked on comes before what there is to work on, and
// what there is to work on is a count and the verbs: the items a prompt
// names arrive on that prompt, below.
put('rules.json', { projects: { alpha: { rules: [
  { name: 'only-rule', text: 'RULESMARK the standing rule', by: 'you' }] } } });
put('bugs.json', { projects: { alpha: [
  { id: 1, title: 'BUGMARK something is wrong with the picker', severity: 'high',
    status: 'open', at: 1750000000, by: 'you' }] } });
const roadmapFile = read('roadmap.json');
roadmapFile.projects = { alpha: [{ id: 1, text: 'ROADMAPMARK a thing to do with the picker', by: 'you',
                                   steps: [{ text: 'first' }, { text: 'second', done: true }] },
                                 { id: 2, text: 'PARKEDMARK a parked one', by: 'you', shelved: 1790000000 }] };
put('roadmap.json', roadmapFile);

p = await pre();
const at = s => p.text.indexOf(s);
ok(at('RULESMARK') >= 0 && /1 open item, and 1 parked by the operator/.test(p.text) && /bug tracker with 1 open \(1 high\)/.test(p.text)
   && !/ROADMAPMARK|BUGMARK|PARKEDMARK/.test(p.text),
   'the rules are in the block whole; the roadmap and the bugs are counts and verbs, no title among them');
ok(at('RULESMARK') < at('shared to-do list') && at('shared to-do list') < at('bug tracker with'),
   '...in that order: how to work on it, then what there is, then what is broken');
ok(!/\n\n\n/.test(p.text) && p.bytes === Buffer.byteLength(p.text, 'utf8') && (p.notes || []).length === 0,
   `...joined by one blank line, the size the block's own (${p.bytes} bytes)`);
ok((p.parts || []).map(x => x.name).join(',') === 'core,rules,briefing,live,roadmap,bugs',
   `...with each named and measured separately, the briefing's core and the rules first (${
     (p.parts || []).map(x => `${x.name} ${x.bytes}`).join(' · ')})`);

// What a prompt names arrives on that prompt, by its words or its number,
// once a conversation, through the hook every prompt runs.
const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const hook = input => execFileSync('python3', [`${REPO}/scripts/dashboard/bb-prompt-relay`, 'alpha', 'u_pre'],
  { input: JSON.stringify(input), encoding: 'utf8',
    env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`,
           XDG_CACHE_HOME: `${DIR}/cache-pre`, BB_ACCOUNT_UID: 'u_pre', BUILDERBOT_ROLE: '' } });
const named = hook({ prompt: 'the picker is wrong: look at the ROADMAPMARK thing to do', session_id: 'pre-1' });
ok(/R1 ROADMAPMARK a thing to do with the picker \(1 step open\): `bb roadmap show R1`/.test(named)
   && /B1 \[high\] BUGMARK something is wrong with the picker: `bb bug show B1`/.test(named),
   `a prompt whose words an open item's or a bug's title shares is handed them, with the verb that prints each (${named.slice(0, 80)})`);
ok(!/ROADMAPMARK/.test(hook({ prompt: 'the picker thing to do, again', session_id: 'pre-1' }))
   && /R1 ROADMAPMARK/.test(hook({ prompt: 'what about R1?', session_id: 'pre-2' }))
   && !/PARKEDMARK/.test(hook({ prompt: 'a parked one', session_id: 'pre-2' }))
   && hook({ prompt: 'something else entirely', session_id: 'pre-3' }).trim() === '',
   '...once a conversation, by number too, never a parked item, and nothing for a prompt that names none');

// ---- a store that contributes nothing leaves no gap -------------------------
put('bugs.json', { projects: {} });
p = await pre();
ok(at('RULESMARK') >= 0 && !/bug tracker/.test(p.text) && !/\n\n\n/.test(p.text)
   && (p.parts || []).map(x => x.name).join(',') === 'core,rules,briefing,live,roadmap',
   'a tracker with nothing open drops out of the block entirely, gap included');
const part = name => (p.parts || []).find(x => x.name === name) || {};
ok(part('rules').share === 16384 && part('roadmap').share === undefined,
   'the rules keep their share of the prompt; a count has none');

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
