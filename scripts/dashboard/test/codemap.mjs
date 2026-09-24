// bb map (roadmap R75): the code map a session asks instead of grepping.
// No browser: the map is a python module over the tree, and what it says
// is checked against facts the tree holds for certain: a function's callers
// this repository's own code makes, a definition's file and line, the ids a
// suite names. Run over this copy of the tree, so the index it writes lands
// beside the copy and never in the checkout.
import { ok, done } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const map = (...args) => execFileSync('python3', [`${REPO}/scripts/lib/codemap.py`, '--root', REPO, ...args],
                                      { encoding: 'utf8' }).trim();

const built = map('build');
ok(/\d+ files \(.*\d+ js.*\d+ py.*\), \d+ definitions, \d+ calls/.test(built),
   `the map builds over the tree and says what it holds (${built.split('\n')[0].slice(0, 90)})`);

// A definition: where, with its span.
const def = map('find', 'openDocker');
ok(/^scripts\/dashboard\/tab-docker\.js:\d+ to \d+  function$/m.test(def),
   `find names a function's file, line and span (${def.split('\n')[0]})`);

// Callers, with the function each call is made from, page and suites apart.
const callers = map('who-calls', 'loadDocker');
ok(/tab-docker\.js:\d+  from openDocker/.test(callers) && /index\.html:\d+  from open/.test(callers),
   'who-calls attributes a call to the function it is made from, through a parameter list with commas');
ok(/^test scripts\/dashboard\/test\/devapp\.mjs/m.test(callers),
   '...and marks the suites among the callers');
ok(!/from \(top level\)  \| async function loadDocker/.test(callers),
   "...without counting a definition's own header as a call of itself");

// What a definition says about itself rides with its address: the comment
// directly above it, or a docstring's first sentence, and nothing where
// nothing sits there. The notes live in the code; the map reads them out.
ok(/^    says: What the panel needs after any change: the list, whether there is anywhere to send, and whether a session has been told about it yet\.$/m.test(map('find', '_roadmap_state')),
   "find hands over a python method's docstring, its first sentence whole");
ok(/^    says: gfx_tool RECIPE NAME: /m.test(map('find', 'gfx_tool')), "...and a shell function's comment");
ok(/^    says: Each terminal tab is an iframe running a full xterm\.js over its own websocket\.$/m.test(map('find', 'roomForTab')),
   "...and a page function's comment block, cut at its first sentence");
ok(!/says:/.test(map('find', 'pinTo')), '...and says nothing for a function with nothing directly above it');

// Python: a method's callers carry the class.
const py = map('who-calls', '_roadmap_state');
ok(/^_roadmap_state: What the panel needs after any change/m.test(py) && /from Handler\._get_todo \(GET \/api\/roadmap\.\)/.test(py),
   "who-calls opens with the callee's sentence and gives each caller its first clause");
ok(/server\.py:\d+  from Handler\._roadmap\b/.test(py), 'a python method is attributed to its class and method');

// Shell: bb's own functions.
const sh = map('who-calls', 'gfx_tool');
ok(/^scripts\/bb:\d+  from tool_graphics/m.test(sh), "bb's shell functions are in the map too");

// What a function draws, and which suites name it.
const draws = map('draws', '.dmtab');
ok(/tab-docker\.js  \w+  \(line/.test(draws) && /^test scripts\/dashboard\/test\/devapp\.mjs  \(\d+ places\)/m.test(draws),
   'draws says which function draws a class and which suites name it, one line per suite');
const id = map('draws', 'roadmapHint');
ok(/index\.html  \(markup\)/.test(id) && /test scripts\/dashboard\/test\/roadmap\.mjs/.test(id),
   'an id in the markup is attributed to the markup, with the suites that name it');

// The suites a change touches: the map's half of a preflight.
const suites = map('suites', 'scripts/dashboard/tab-docker.js');
ok(/^scripts\/dashboard\/test\/devapp\.mjs  \(\d+:/m.test(suites),
   `suites FILE names the suites that reach what the file draws, most first (${suites.split('\n')[0].slice(0, 70)})`);

// A python change reaches its suites through the server's route table: the
// module's functions are called from a handler, the handler answers a path,
// the suite asks it. Only calls INTO the module count (roadmap.items), and
// the walk goes through the handler's own methods, never a module-level
// helper: by name alone `load` reached every store and every suite.
const pyS = map('suites', 'scripts/dashboard/roadmap.py');
ok(/^scripts\/dashboard\/test\/roadmap\.mjs  \(\d+: .*\/api\/roadmap/m.test(pyS),
   'a python module finds the suites that ask the paths its handlers answer');
ok(!/auth\.mjs  \(\d+: \/api\/bugs/.test(pyS), '...and not every suite that asks any path');
ok(/^scripts\/dashboard\/test\/agent\.mjs  \(\d+: .*scripts\/bb/m.test(map('suites', 'scripts/bb')),
   'a file a suite names outright, such as bb itself, reaches that suite');
const names = map('suites', 'scripts/dashboard/toolchains.py', '--names').split('\n');
ok(names.includes('toolchains') && !names.some(n => n.startsWith('lab-')),
   `--names gives one suite per line for a script, lab suites left out (${names.join(', ')})`);

// bb tests preflight: the plan from named files (the copy this runs in has
// no .git, so the branch half is not asked here).
const pre = (...files) => execFileSync('bash', [`${REPO}/scripts/bb`, 'tests', 'preflight', '--dry', '--files', ...files],
                                       { encoding: 'utf8', env: { ...process.env, BB_TREE: REPO } });
const plan = pre('scripts/dashboard/tab-docker.js');
ok(/suites:.*\bdevapp\b/.test(plan) && /checks:\s+lint voice design/.test(plan),
   `a dashboard change plans its suites and the design check (${plan.match(/suites:.*/)?.[0].slice(0, 60)})`);
ok(/suites:\s+ALL/.test(pre('scripts/dashboard/server.py')), 'a change to server.py is the whole suite, said as such');
ok(/suites:\s+none/.test(pre('README.md')) && /checks:\s+lint voice$/m.test(pre('README.md')),
   'a change with no suite still gets the lint and voice checks');

// The other C-shaped languages: the companion app's Kotlin. `fun` opens a
// definition, a trailing lambda (Row(...) { ... }) is a call and not a
// method, and a default lambda in a parameter list does not open the body.
const kt = map('defs', 'android/app/src/main/java/dev/builderbot/app/ui/Parts.kt');
ok(/^\d+-\d+  function Pill$/m.test(kt) && /function Panel/.test(kt), 'Kotlin functions are definitions with their span');
const pill = map('who-calls', 'Pill');
ok(/ProjectScreen\.kt:\d+  from Roadmap\b/.test(pill) && /Screens\.kt:\d+  from HomeScreen\b/.test(pill) && !/from Row\b/.test(pill),
   'a Compose call is attributed to the composable it sits in, not to the Row whose lambda holds it');

// Dead code by measurement (R76 step 1): a function nothing calls AND
// nothing passes by name. A handler handed to onclick without a call is a
// use; only a function no token anywhere names is unused. Proved on a file
// written into this copy, since the tree's own page has none.
{
  const dead = `${REPO}/scripts/dashboard/zz-probe-dead.js`;
  writeFileSync(dead, 'function neverUsedAnywhere(){ return 1; }\nfunction handedOver(){ return 2; }\nconst pick = handedOver;\n');
  const un = map('unused', 'scripts/dashboard/zz-probe-dead.js');
  ok(/neverUsedAnywhere/.test(un) && !/handedOver/.test(un),
     'unused lists the function no token names, and not the one passed by name');
  // ...and who-calls says where it was passed, rather than "nothing calls"
  // and silence (B222): the answer that read a live handler as dead.
  const wc = map('who-calls', 'handedOver');
  ok(/^nothing calls handedOver directly; it is passed by name:/m.test(wc)
     && /zz-probe-dead\.js:3  passed by name in \(top level\)  \| const pick = handedOver;/.test(wc),
     'who-calls lists the places a function is passed by name, with the function each sits in');
  ok(/nothing calls neverUsedAnywhere, and nothing passes it by name/.test(map('who-calls', 'neverUsedAnywhere')),
     '...and says both halves when neither happens');
  execFileSync('rm', ['-f', dead]);
}

// ...and in python (B227): devapp.py hands its compose job runner to the
// jobs module by name, which read as nothing passing it.
ok(/devapp\.py:\d+  passed by name in configure  \| .*runner\.register\("compose", run_compose_job\)/.test(map('who-calls', 'run_compose_job')),
   'a python function passed by name is seen where it is passed, in the function that passes it');

// A plan keeps its words and its addresses move under it (item 7 of the
// 23 Sep list): `file ~line` in the roadmap's details is checked against
// where the name beside it is now, and a name that is nowhere is said.
{
  const txt = `${REPO}/.bb-map/probe-addresses.txt`;
  const at = map('find', 'openDocker').match(/:(\d+)/)[1];      // a true address, wherever it is today
  writeFileSync(txt, ['  R2  a plan', '       details: The picker is pinTo() in scripts/dashboard/index.html (~4634), and',
                      '~ R3  another, shelved', `       details: imgAdder() in index.html (~8093); openDocker (tab-docker.js ~${at}) draws it.`, ''].join('\n'));
  const adr = map('addresses', txt);
  ok(/^  R2: ~4634  pinTo is scripts\/dashboard\/index\.html:\d+ now$/m.test(adr),
     'an address more than twenty lines from its name is reported with where the name is now, under its item');
  ok(/^  R3: ~8093  imgAdder is defined nowhere the map looks now \(was index\.html;/m.test(adr),
     '...a name that is gone is said to be gone, under a shelved item too');
  ok(/^1 address still inside the name beside it, 0 with no name/m.test(adr),
     '...and one that still holds is counted, not listed');
  execFileSync('rm', ['-f', txt]);
}

// An arrow with an expression body is a function too (B224): `const
// drawLinux = () => drawShellCard(...)` was in no answer at all, so a
// refactor read it as nothing. Found, and seen passed by name.
ok(/^scripts\/dashboard\/page-commands\.js:\d+  arrow$/m.test(map('find', 'drawLinux')),
   'an expression-bodied arrow is a definition');
ok(/index\.html:\d+  passed by name in refresh  \| .*drawCard\("linux", drawLinux\)/.test(map('who-calls', 'drawLinux')),
   '...and who-calls sees it handed to the card draw');

// The page's mutable state (B223): every page-level `let`, where it is
// assigned and from what. A binding fed from `state` is a copy of the poll
// kept by hand, which is how B213 and B215 happened; the view puts those
// first so a sweep starts there. Proved on a file written into this copy.
{
  const st = `${REPO}/scripts/dashboard/zz-probe-state.js`;
  writeFileSync(st, ['let mirror = null, timer = null;', 'let cache = null;', 'let count = 0;',
                     'function refresh(){ mirror = state.thing; }',
                     'async function load(){ cache = await (await fetch("/x")).json(); }',
                     'function tick(){ timer = setTimeout(tick, 1000); count++; }', ''].join('\n'));
  const view = map('state', 'scripts/dashboard/zz-probe-state.js');
  const at = n => view.split('\n').findIndex(l => new RegExp(`  ${n}: `).test(l));
  ok(/^4 page-level bindings in zz-probe-state\.js: 1 assigned from state, 1 from a fetch, 2 local/m.test(view),
     `state counts the bindings and sorts them by what feeds them (${view.split('\n')[0]})`);
  ok(/zz-probe-state\.js:1  mirror: 1 assignment\n      scripts\/dashboard\/zz-probe-state\.js:4  in refresh  from state/.test(view),
     'a binding assigned from state names the site, the function and the source');
  ok(/zz-probe-state\.js:2  cache: 1 assignment\n      scripts\/dashboard\/zz-probe-state\.js:5  in load  from a fetch/.test(view),
     '...one assigned from a fetch says so');
  ok(/zz-probe-state\.js:1  timer: 1 assignment, local/.test(view) && /count: 1 assignment, local/.test(view),
     '...a timer and a counter read as local, the second on its first line and ++ counted as an assignment');
  ok(at('mirror') < at('cache') && at('cache') < at('timer'), 'state first, then fetches, then the local ones');
  execFileSync('rm', ['-f', st]);
}

// Coverage (R76 steps 2 to 4): the instrumenter puts a counter at the head
// of every function body it knows the position of, and a merged count file
// answers which suites reached a function.
{
  const dir = `${REPO}/.bb-map/probe-dash`;
  execFileSync('rm', ['-rf', dir]); execFileSync('mkdir', ['-p', dir]);
  for (const f of ['tab-docker.js', 'index.html', 'nb-roadmap.js'])
    execFileSync('cp', [`${REPO}/scripts/dashboard/${f}`, `${dir}/${f}`]);
  const said = execFileSync('python3', [`${REPO}/scripts/lib/codemap.py`, 'instrument', dir], { encoding: 'utf8' });
  const inst = readFileSync(`${dir}/tab-docker.js`, 'utf8');
  ok(/instrumented \d+ functions in 3 files/.test(said) && /async function loadDocker\(\)\{__bbcov\("scripts\/dashboard\/tab-docker\.js:loadDocker#1"\);/.test(inst),
     `the instrumenter counts a function body at its opening brace, keyed by name and ordinal so a line shift keeps the count (${said.trim()})`);
  ok(/<script>var __bbcovc/.test(readFileSync(`${dir}/index.html`, 'utf8')), '...and defines the counter at the head of the page');
  execFileSync('node', ['--check', `${dir}/tab-docker.js`]); execFileSync('node', ['--check', `${dir}/nb-roadmap.js`]);
  ok(true, '...and the instrumented scripts still parse');
  const counts = `${dir}/probe-suite.json`;
  writeFileSync(counts, JSON.stringify({ suite: 'probe-suite', counts: { 'scripts/dashboard/tab-docker.js:loadDocker#1': 3 } }));
  const covFile = `${REPO}/.bb-map/coverage.json`;
  const before = existsSync(covFile) ? readFileSync(covFile, 'utf8') : null;
  map('coverage-ingest', counts);
  ok(/loadDocker: reached by \d+ suites?: .*probe-suite \(3\)/.test(map('covered', 'loadDocker')),
     'covered NAME names the suite that ran it and how often');
  const unc = map('uncovered', 'scripts/dashboard/tab-docker.js');
  ok(/^\d+ functions? no suite reached in scripts\/dashboard\/tab-docker\.js:/.test(unc) || /every function here was reached/.test(unc),
     `uncovered FILE lists what no suite reached (${unc.split('\n')[0].slice(0, 60)})`);
  ok(!/\bloadDocker\b/.test(unc), '...and not the one the ingested counts reached');
  execFileSync('rm', ['-rf', dir]);
  if (before === null) execFileSync('rm', ['-f', `${REPO}/.bb-map/coverage.json`]); else writeFileSync(`${REPO}/.bb-map/coverage.json`, before);
}

// A file by its sections: the unit a cleanup moves, with what reaches in
// from outside and what runs at load, which is what decides whether a
// section can leave the page whole.
const sec = map('sections', 'scripts/dashboard/index.html');
ok(/^scripts\/dashboard\/index\.html: \d+ sections, \d+ top-level definitions$/m.test(sec)
   && /^\s+\d+  the welcome panel: the guide, and the changelog: \d+ functions, \d+ callers? from outside/m.test(sec)
   && /^\s+\d+  tabs: \d+ functions, \d+ callers from outside/m.test(sec),
   'sections lists a file by its headers with each section\'s functions and outside callers');

// Nested definitions are shown under their parent.
const defs = map('defs', 'scripts/dashboard/nb-roadmap.js');
ok(/^\d+-\d+  function nbRoadmapView$/m.test(defs) && /^  \d+-\d+  function drawRoadmap  \(in nbRoadmapView\)$/m.test(defs)
   && /^  \d+-\d+  arrow onclick  \(in drawRoadmap\)/m.test(defs),
   'defs lists a file top down, a function under the closure it lives in and a callback under its function');

// It rebuilds itself when a source is newer, and not otherwise.
const stamp = () => readFileSync(`${REPO}/.bb-map/map3.json`, 'utf8').match(/"built": ([\d.]+)/)[1];
const before = stamp();
map('find', 'openDocker');
ok(stamp() === before, 'a query on an unchanged tree does not rebuild');
execFileSync('touch', [`${REPO}/scripts/dashboard/tab-docker.js`]);
map('find', 'openDocker');
ok(stamp() !== before, '...and a source newer than the index does');
ok(/\(1 file scanned\)/.test(map()), '...rescanning that file alone and keeping the rest');

// An index of another format is rebuilt, never read: the first map crashed
// with a KeyError on every question when it met a newer index on the tree.
{
  const f = `${REPO}/.bb-map/map3.json`;
  const good = readFileSync(f, 'utf8');
  writeFileSync(f, JSON.stringify({ built: 1, files: { 'scripts/bb': { mtime: 1, lang: 'sh' } }, defs: [], calls: [], draws: [] }));
  ok(/^scripts\/dashboard\/tab-docker\.js:\d+ to \d+  function$/m.test(map('find', 'openDocker')),
     'an index of another format is rebuilt and the question answered');
  writeFileSync(f, good);
}

// Refusals say what to type.
let said = '';
try { execFileSync('python3', [`${REPO}/scripts/lib/codemap.py`, '--root', REPO, 'nope'], { encoding: 'utf8', stdio: 'pipe' }); }
catch (e) { said = String(e.stderr); }
ok(/no verb called nope; bb map -h lists them/.test(said), 'an unknown verb is refused with the way out');
ok(/nothing defines noSuchFunctionAnywhere/.test(map('find', 'noSuchFunctionAnywhere')),
   'an unknown name gets a sentence, not an empty screen');

await done(null);
