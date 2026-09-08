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
// Written, a rule is READ: its name, its words and its triggers, no fields —
// every row opening as a form read as a tab of half-finished edits. Edit
// brings the fields back for that one row; Done puts them away.
await page.waitForFunction(() => document.querySelectorAll('#rulesBox .rulerow').length === 2
                                 && !document.querySelector('#rulesBox .rulerow .rlText'), null, { timeout: 10000 });
ok(await page.$eval('#rulesBox .rulerow[data-i="1"]', r =>
     r.tagName === 'DETAILS' && !r.open
     && /agent-compat/.test(r.querySelector('summary .rlNameRO')?.textContent || '')
     && /add, do not change/.test(r.querySelector('.rlBody')?.textContent || '')
     && /scripts\/agent/.test(r.querySelector('.rltrig')?.textContent || '')
     && !r.querySelector('textarea, input')),
   'a saved rule is a closed fold with its name on the line and its words behind it, not fields');
ok(await page.$eval('#rulesBox .rulerow[data-i="1"]', r => getComputedStyle(r).borderRadius === '0px'
     && getComputedStyle(r).borderTopWidth === '1px'),
   '...drawn as a line-divided row like a bug report, not a box');
await page.click('#rulesBox .rulerow[data-i="1"] summary');
await page.waitForFunction(() => document.querySelector('#rulesBox .rulerow[data-i="1"]').open, null, { timeout: 10000 });
await page.click('#rulesBox .rulerow[data-i="1"] .rlEdit');
await page.waitForSelector('#rulesBox .rulerow[data-i="1"] .rlText', { timeout: 10000 });
ok(await page.$('#rulesBox .rulerow[data-i="0"] .rlText') === null,
   'Edit opens that rule\'s fields and no other\'s');
await page.click('#rulesBox .rulerow[data-i="1"] .rlDone');
await page.waitForFunction(() => !document.querySelector('#rulesBox .rulerow .rlText'), null, { timeout: 10000 });
ok(true, '...and Done puts them away again');

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

// ---- a rule that carries a framework (roadmap R31) --------------------------
// The document that defines it and the command that checks it ride on the
// rule; the block names both, and `bb rules check` runs the command in the
// tree for the rules whose files changed.
ok(/added design/.test(bb('add', 'design', 'New surface uses the framework.', '--files', 'src',
                          '--doc', 'docs/design.md', '--check', 'test -d .git')),
   'a rule takes a doc and a check');
ok(read().find(r => r.name === 'design')?.doc === 'docs/design.md'
   && read().find(r => r.name === 'design')?.check === 'test -d .git',
   '...stored on it');
ok(/defined in full in docs\/design\.md/.test(bb('--prompt'))
   && /bb rules check design/.test(bb('--prompt')),
   'the block a session is handed says where it is defined and how it is checked');
ok(/PASS  design/.test(bb('check', 'design')),
   'bb rules check NAME runs the check in the project tree and reports it');
ok(/nothing changed here that a rule/.test(bb('check')),
   '...and with nothing changed under a rule\'s files, bare check has nothing to run');
{
  const { writeFileSync: wf, mkdirSync: mk } = await import('node:fs');
  mk(`${DIR}/ws/alpha/src`, { recursive: true });
  wf(`${DIR}/ws/alpha/src/new.txt`, 'changed under the rule\n');
  ok(/== design/.test(bb('check')), '...while a new file under its files makes bare check run it');
  bb('edit', 'design', '--check', 'false');
  let out = '';
  try { bb('check', 'design'); } catch (e) { out = String(e.stdout || ''); }
  ok(/FAIL  design/.test(out), 'a failing check fails by name, with a non-zero exit');
  ok(/checked by: false/.test(bb('show', 'design')), 'bb rules show prints the doc and the check');
}

// ---- reading them from a session -------------------------------------------
ok(/No em dashes/.test(bb('list')) && /agent-compat/.test(bb('list')),
   'bb rules lists what is in effect');
ok(/add, do not change/.test(bb('show', 'agent-compat')),
   'bb rules show reads one in full — how a session follows the name in its block');
// What a session may NOT do is the narrow part, and it is about the whole
// list rather than about writing at all: the tab's replace is a person's,
// because one call rewriting every rule is exactly what the per-rule
// ownership check exists to stop.
let refused = '';
try { execFileSync(BB, ['rules', 'replace'], { env: ENV }); }
catch (e) { refused = String(e.stdout || '') + String(e.stderr || ''); }
ok(/unknown/.test(refused),
   'there is no verb that rewrites the whole list — that one is the tab\'s');

// ---- a session's own rules -------------------------------------------------
// Both sides write these, the way both sides write the roadmap and the
// tracker. What is asymmetric is narrower than "who may write": a session may
// leave a rule and change its own, and may not touch one of the operator's.
ok(/added dont-edit-during-a-suite/.test(
     bb('add', 'dont edit during a suite',
        'The page is served from disk per request, so a mid-run edit is tested.',
        '--words', 'suite, test')),
   'a session can leave a rule of its own');
ok(read().find(r => r.name === 'dont-edit-during-a-suite')?.by === 'claude',
   '...marked as its own, which is what decides who may change it later');
ok(/reworded/.test(bb('edit', 'dont-edit-during-a-suite', 'Stage edits; apply after.')),
   '...and change it');
{
  let no = '';
  try { bb('edit', 'voice', 'no em dashes, and no semicolons either'); }
  catch (e) { no = String(e.stdout || '') + String(e.stderr || ''); }
  ok(/the operator's/.test(no) && /cannot change it/.test(no),
     '...and cannot touch one of the operator\'s, being told which it is');
  ok(read().find(r => r.name === 'voice').text === 'No em dashes.',
     '...and nothing moved when it tried');
}
ok(/\*dont-edit-during-a-suite/.test(bb('list')),
   'the listing marks which are a session\'s, since that is what decides what it may do');
ok(/\[yours\]/.test(bb('--prompt')),
   'and the block says so too — a session\'s own note must not reach the next one '
   + 'wearing the operator\'s authority');
{
  const h = bb('history');
  ok(/claude\s+add\s+dont-edit-during-a-suite/.test(h) && /you\s+add\s+voice/.test(h),
     'every change is in a history that says who made it — which is what makes '
     + 'this safe to share, rather than a lock');
}
ok(/dropped dont-edit-during-a-suite/.test(
     bb('rm', 'dont-edit-during-a-suite', 'it belongs in CLAUDE.md now')),
   'a session can drop its own, with the reason kept');

// The endpoint, not just the verb. `bb rules` has no write verb and the file
// tools are denied on the file — but a session has a shell and a token, and
// that token authenticates as a principal with user rights over exactly this
// project. Without a refusal here the HTTP route would have been the way
// around the whole arrangement, which is the kind of hole a design like this
// is worth nothing without.
{
  // A real one, minted the way bb-tty mints the token it hands a session:
  // the point is a genuine session principal, not a shape.
  const tok = execFileSync('python3', ['-c', `
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('users', ${
  JSON.stringify(join(HERE, '..', 'users.py'))})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import json
def wj(path, d):
    tmp = str(path) + '.new'
    with open(tmp, 'w') as f: json.dump(d, f, indent=2)
    os.replace(tmp, path)
m.configure(state=${JSON.stringify(`${DIR}/state`)}, write_json=wj)
print(m.mint_session('alpha'))
`], { encoding: 'utf8' }).trim();
  ok(/^bbs_/.test(tok), 'a session token can be minted for the check below');
  // From outside the browser, which is where a session actually is: a shell
  // with a token and no cookie. Through the page it would have carried the
  // operator's own login as well, and proved nothing.
  const res = await fetch(URL.replace(/\/$/, '') + '/api/rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
    body: JSON.stringify({ project: 'alpha', action: 'save',
                           rules: [{ name: 'mine', text: 'a session wrote this' }] }) });
  const r = { status: res.status, body: await res.text() };
  ok(r.status === 403, `a session's own token cannot write a rule (${r.status} ${
    JSON.stringify(r.body).slice(0, 200)}, token ${tok.slice(0, 10)}…)`);
  ok(/being held to/.test(r.body),
     '...and is told why rather than getting a bare no');
  ok(!read().some(x => x.name === 'mine'),
     '...and nothing was written');
}

ok(page.errors.length === 0, `zero console errors${
  page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
