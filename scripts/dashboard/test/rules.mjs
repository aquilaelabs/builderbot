// The operator's house rules (roadmap #7): the one thing in the notebook a
// session reads and cannot write.
//
// What is exercised for real: the store through `bb rules`, the tab through
// the page, the standing block exactly as bb-tty composes it, and both hooks
// with the JSON a real Claude Code would hand them. What is faked: nothing —
// the hooks are the shipped scripts, run as processes, because "does the rule
// reach the session" is the only question this file is about and a stub of
// the hook would be a stub of the answer.
import { launch, newPage, ok, done, ready, URL, DIR, nbShown, nbTab, sleep } from './lib.mjs';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const BB = join(HERE, '..', '..', 'bb');
const FILE = `${DIR}/state/rules.json`;
const ENV = { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
              DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`,
              BB_PROJECT: 'alpha' };
const bb = (...a) => execFileSync(BB, ['rules', ...a], { env: ENV }).toString();
const read = () => existsSync(FILE)
  ? JSON.parse(readFileSync(FILE, 'utf8')).projects.alpha?.rules || [] : [];
// A hook, run the way Claude Code runs one: JSON on stdin, stdout to the model.
const hook = (name, argv, body) => execFileSync(join(HERE, '..', name), argv,
  { env: { ...ENV, BB_TREE: `${DIR}/ws/alpha` },
    input: JSON.stringify(body) }).toString();

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

// ---- the tab ---------------------------------------------------------------
await page.click(`#projects .row:has(.name:text-is("alpha")) [data-m]`);
await nbShown(page);
await nbTab(page, 'briefing');
await page.waitForSelector('#rulesBox .sect', { timeout: 15000 });
ok(/Nothing set/.test(await page.$eval('#rulesBox', e => e.textContent)),
   'a project with no rules says so, and says what a rule is for');
ok(await page.$('#memList') !== null,
   '...on the same tab as the memories, which is the point of the rename');

// Two rules: one standing, one with a trigger. There is no picker for which
// kind — the trigger is the answer, and the row says which it became.
await page.click('#rlAdd');
await page.waitForSelector('#rulesBox .rulerow', { timeout: 10000 });
await page.fill('#rulesBox .rulerow .rlName', 'voice');
await page.fill('#rulesBox .rulerow .rlText', 'No em dashes.');
ok((await page.$eval('#rulesBox .rulerow .rlkind', e => e.textContent)).includes('every session'),
   'a rule with no trigger is one every session gets');
await page.click('#rlAdd');
await page.waitForFunction(() => document.querySelectorAll('#rulesBox .rulerow').length === 2,
                           { timeout: 10000 });
const two = '#rulesBox .rulerow[data-i="1"]';
await page.fill(`${two} .rlName`, 'agent compat');
await page.fill(`${two} .rlText`,
  'How the agent is versioned here.\nThe window is the project minor: add, do not change.');
await page.fill(`${two} .rlPaths`, 'scripts/agent');
await page.fill(`${two} .rlWords`, 'agent, protocol');
ok((await page.$eval(`${two} .rlkind`, e => e.textContent)).includes('on its triggers'),
   '...and one with a trigger says so the moment the trigger is typed');
ok(!await page.$eval('#todoSaveQuiet', b => b.disabled),
   'a written rule arms the panel\'s one Save, like everything else here');
ok(read().length === 0, '...and nothing is on disk until it is pressed');

await page.click('#todoSaveQuiet');
await page.waitForFunction(() => document.getElementById('todoSaveQuiet')
                             .getAttribute('aria-busy') !== 'true', { timeout: 15000 });
const saved = read();
ok(saved.length === 2 && saved[0].name === 'voice',
   'Save writes them');
ok(saved[1].name === 'agent-compat',
   '...slugging a name that was typed with a space rather than refusing it');
ok(JSON.stringify(saved[1].paths) === '["scripts/agent"]'
   && JSON.stringify(saved[1].words) === '["agent","protocol"]',
   `...and splitting the triggers on the comma they were typed with (${
     JSON.stringify(saved[1])})`);

// ---- what a session is handed ----------------------------------------------
// Exactly what bb-tty puts in front of one: `bb rules --prompt`.
const block = bb('--prompt');
ok(/No em dashes\./.test(block),
   'the standing rule is in the block every session here starts with');
ok(!/add, do not change/.test(block),
   `...and the conditional one is NOT, which is the whole reason it is a kind (${
     JSON.stringify(block)})`);
ok(/agent-compat/.test(block) && /bb rules show/.test(block),
   '...but it is named there, so a trigger that misses leaves a rule the session knows of');
ok(/cannot change them/.test(block),
   '...and the block says whose they are');

// ---- the two hooks ---------------------------------------------------------
const asked = hook('bb-prompt-relay', ['alpha', 'u_test'],
                   { prompt: 'have a look at the agent again' });
ok(/add, do not change/.test(asked),
   'a word in the prompt brings the rule it names, on that turn');
ok(!/add, do not change/.test(
     hook('bb-prompt-relay', ['alpha', 'u_test'], { prompt: 'restyle the memory tab' })),
   '...and a prompt it does not cover brings nothing');
const edit = hook('bb-work-note', ['alpha', 'u_test'],
                  { tool_name: 'Edit',
                    tool_input: { file_path: `${DIR}/ws/alpha/scripts/agent/x.py` } });
ok(/add, do not change/.test(edit),
   `a file about to be edited brings the rule that covers it, before the edit (${
     JSON.stringify(edit).slice(0, 200)})`);
ok(!/add, do not change/.test(
     hook('bb-work-note', ['alpha', 'u_test'],
          { tool_name: 'Edit', tool_input: { file_path: `${DIR}/ws/alpha/README.md` } })),
   '...and a file it does not cover brings nothing');

// ---- reading them from a session -------------------------------------------
ok(/No em dashes/.test(bb('list')) && /agent-compat/.test(bb('list')),
   'bb rules lists what is in effect');
ok(/add, do not change/.test(bb('show', 'agent-compat')),
   'bb rules show reads one in full — how a session follows the name in its block');
let refused = '';
try { execFileSync(BB, ['rules', 'add', 'x'], { env: ENV }); }
catch (e) { refused = String(e.stdout || '') + String(e.stderr || ''); }
ok(/unknown/.test(refused),
   'there is no verb here that writes one: a rule a session could set is not a rule');

ok(page.errors.length === 0, `zero console errors${
  page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
