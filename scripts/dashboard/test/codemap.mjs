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

// Python: a method's callers carry the class.
const py = map('who-calls', '_roadmap_state');
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
  execFileSync('rm', ['-f', dead]);
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
  ok(/instrumented \d+ functions in 3 files/.test(said) && /async function loadDocker\(\)\{__bbcov\("scripts\/dashboard\/tab-docker\.js:\d+:loadDocker"\);/.test(inst),
     `the instrumenter counts a function body at its opening brace (${said.trim()})`);
  ok(/<script>var __bbcovc/.test(readFileSync(`${dir}/index.html`, 'utf8')), '...and defines the counter at the head of the page');
  execFileSync('node', ['--check', `${dir}/tab-docker.js`]); execFileSync('node', ['--check', `${dir}/nb-roadmap.js`]);
  ok(true, '...and the instrumented scripts still parse');
  const line = inst.match(/tab-docker\.js:(\d+):loadDocker/)[1];
  const counts = `${dir}/probe-suite.json`;
  writeFileSync(counts, JSON.stringify({ suite: 'probe-suite', counts: { [`scripts/dashboard/tab-docker.js:${line}:loadDocker`]: 3 } }));
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

// Nested definitions are shown under their parent.
const defs = map('defs', 'scripts/dashboard/nb-roadmap.js');
ok(/^\d+-\d+  function nbRoadmapView$/m.test(defs) && /^  \d+-\d+  function drawRoadmap  \(in nbRoadmapView\)$/m.test(defs)
   && /^  \d+-\d+  arrow onclick  \(in drawRoadmap\)/m.test(defs),
   'defs lists a file top down, a function under the closure it lives in and a callback under its function');

// It rebuilds itself when a source is newer, and not otherwise.
const stamp = () => readFileSync(`${REPO}/.bb-map/map2.json`, 'utf8').match(/"built": ([\d.]+)/)[1];
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
  const f = `${REPO}/.bb-map/map2.json`;
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
