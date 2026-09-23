// bb map (roadmap R75): the code map a session asks instead of grepping.
// No browser: the map is a python module over the tree, and what it says
// is checked against facts the tree holds for certain: a function's callers
// this repository's own code makes, a definition's file and line, the ids a
// suite names. Run over this copy of the tree, so the index it writes lands
// beside the copy and never in the checkout.
import { ok, done } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

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

// Nested definitions are shown under their parent.
const defs = map('defs', 'scripts/dashboard/nb-roadmap.js');
ok(/^\d+-\d+  function drawRoadmap$/m.test(defs) && /^  \d+-\d+  arrow onclick  \(in drawRoadmap\)/m.test(defs),
   'defs lists a file top down, a callback under the function it lives in');

// It rebuilds itself when a source is newer, and not otherwise.
const stamp = () => readFileSync(`${REPO}/.bb-map/index.json`, 'utf8').match(/"built": ([\d.]+)/)[1];
const before = stamp();
map('find', 'openDocker');
ok(stamp() === before, 'a query on an unchanged tree does not rebuild');
execFileSync('touch', [`${REPO}/scripts/dashboard/tab-docker.js`]);
map('find', 'openDocker');
ok(stamp() !== before, '...and a source newer than the index does');

// Refusals say what to type.
let said = '';
try { execFileSync('python3', [`${REPO}/scripts/lib/codemap.py`, '--root', REPO, 'nope'], { encoding: 'utf8', stdio: 'pipe' }); }
catch (e) { said = String(e.stderr); }
ok(/no verb called nope; bb map -h lists them/.test(said), 'an unknown verb is refused with the way out');
ok(/nothing defines noSuchFunctionAnywhere/.test(map('find', 'noSuchFunctionAnywhere')),
   'an unknown name gets a sentence, not an empty screen');

await done(null);
