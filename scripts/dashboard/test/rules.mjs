// The operator's house rules (roadmap #7): the one thing in the notebook a
// session reads and cannot write.
//
// What is exercised for real: the store through `bb rules`, the tab through
// the page, the standing block exactly as bb-tty composes it, and both hooks
// with the JSON a real Claude Code would hand them. What is faked: nothing.
// The hooks are the shipped scripts, run as processes, because "does the rule
// reach the session" is the only question this file is about and a stub of
// the hook would be a stub of the answer.
import { launch, newPage, ok, done, ready, URL, DIR, nbShown, nbTab, sleep, openFold } from './lib.mjs';
import { readFileSync, existsSync, writeFileSync } from 'node:fs';
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
// ---- the code base, counted, above the rules ---------------------------------
// What git tracks in the project by language, with the files and the lines:
// the tab's first section. alpha is a repository with one tracked file, so
// the count is small and exact, and dist/ and the rest of the fixture's
// untracked litter are not in it.
// Tracked means tracked: alpha's working tree has files, but only what is
// in git's index counts, so two files are committed first (a script and
// the README), and dist/, the untracked archive fixtures and the like stay
// out of the number.
writeFileSync(`${DIR}/ws/alpha/count.py`, 'print("one")\nprint("two")\n');
const genv = { ...process.env, GIT_AUTHOR_NAME: 't', GIT_AUTHOR_EMAIL: 't@x', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@x' };
execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'add', 'count.py', 'README.md'], { env: genv });
execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'commit', '-q', '-m', 'two files to count'], { env: genv });
await page.evaluate(() => { const b = document.querySelector('.nbtabs [data-v="roadmap"]'); b && b.click(); });
await nbTab(page, 'briefing');
await page.waitForFunction(() => /2 files/.test(document.querySelector('#rulesBox .sect .sst')?.textContent || ''), null, { timeout: 15000 });
const sects = await page.$$eval('#rulesBox .sect', ss => ss.map(s => s.querySelector('.stitle, .shead, summary')?.textContent || s.textContent.slice(0, 40)));
ok(/Code base/.test(sects[0] || '') && /Your rules/.test(sects[1] || ''),
   `the code base section comes first, the rules after it (${sects.map(x => x.trim().slice(0, 20)).join(' | ')})`);
const cb = await (await fetch(URL + 'api/codebase?project=alpha', { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json();
ok(cb.files === 2 && cb.lines === 3 && cb.code_lines === 2
   && cb.languages.some(l => l.name === 'Python' && l.lines === 2 && l.pct === 100)
   && cb.languages.some(l => l.name === 'Markdown' && l.kind === 'prose'),
   `the count is git's tracked files by language, and only those (${cb.files} files, ${cb.lines} lines: ${cb.languages.map(l => l.name + ' ' + l.lines).join(', ')})`);
ok(new RegExp(`${cb.files} file`).test(await page.$eval('#rulesBox .sect', e => e.textContent))
   && /tracked by git/.test(await page.$eval('#rulesBox .sect', e => e.textContent)),
   '...and the section says the files, the lines, and that it is git that decides what counts');
const nogit = await (await fetch(URL + 'api/codebase?project=gamma', { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json();
ok(/not a git repository/.test(nogit.error || ''), 'a project that is not a repository says so rather than counting nothing');
ok(await page.$('#memList') !== null,
   '...on the same tab as the memories, which is the point of the rename');

// Two rules: one standing, one with a trigger. There is no picker for which
// kind: the trigger is the answer, and the row says which it became.
//
// The rules section is shut by default now. The code base above it is the
// answer this tab opens on, and the count on this heading says what is
// behind it, so everything in it, Add included, is one fold away.
await openFold(page, '#rulesBox details.sect[data-sect="briefing:rules"]');
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
ok(!await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   'a written rule arms the panel\'s one Save, like everything else here');
ok(read().length === 0, '...and nothing is on disk until it is pressed');

await page.click('#roadmapSaveQuiet');
await page.waitForFunction(() => document.getElementById('roadmapSaveQuiet')
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
// Written, a rule is READ: its name, its words and its triggers, no fields.
// Every row opening as a form read as a tab of half-finished edits. Edit
// brings the fields back for that one row; Cancel puts them away and drops
// what was typed into them.
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
await page.fill('#rulesBox .rulerow[data-i="1"] .rlText', 'typed, then thought better of');
ok(!await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   'typing into a rule arms the panel\'s Save');
await page.click('#rulesBox .rulerow[data-i="1"] .rlCancel');
await page.waitForFunction(() => !document.querySelector('#rulesBox .rulerow .rlText'), null, { timeout: 10000 });
ok(/add, do not change/.test(await page.$eval('#rulesBox .rulerow[data-i="1"] .rlBody', e => e.textContent)),
   '...and Cancel puts them away, reading what was there before Edit');
ok(await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   '...with nothing left staged, so the Save goes quiet again');
// A row Add made has nothing to go back to: cancelling it is removing it.
await page.click('#rlAdd');
await page.waitForFunction(() => document.querySelectorAll('#rulesBox .rulerow').length === 3, null, { timeout: 10000 });
await page.click('#rulesBox .rulerow[data-i="2"] .rlCancel');
await page.waitForFunction(() => document.querySelectorAll('#rulesBox .rulerow').length === 2
                                 && !document.querySelector('#rulesBox .rulerow .rlText'), null, { timeout: 10000 });
ok(await page.$eval('#roadmapSaveQuiet', b => b.disabled),
   'cancelling a row that Add made takes the row away and stages nothing');

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

  // ---- the Stop hook (R31, step 2): a failing check refuses the stop ------
  // Run the way Claude Code runs it: JSON on stdin, JSON on stdout. The
  // design rule's check is `false` and src/new.txt is a changed file under
  // its files, so the stop is refused with the failure; a stop a hook already
  // refused once is let through; a passing check writes a stamp, and the same
  // tree is not checked twice.
  const cache = `${DIR}/cache-check`;
  const stop = body => execFileSync('python3', [join(HERE, '..', 'bb-check-relay'), 'alpha', 'u_test'],
    { env: { ...ENV, BB_TREE: `${DIR}/ws/alpha`, XDG_CACHE_HOME: cache }, input: JSON.stringify(body) }).toString();
  const refused = stop({ stop_hook_active: false });
  ok(/"decision": "block"/.test(refused) && /FAIL  design/.test(refused),
     'the Stop hook refuses the stop with the failing check named');
  ok(stop({ stop_hook_active: true }) === '',
     '...but lets a stop through that a hook already refused once, so it never loops');
  bb('edit', 'design', '--check', 'test -d .git');
  ok(stop({ stop_hook_active: false }) === '' && existsSync(`${cache}/builderbot/u/_none/project/alpha/checked`),
     'a passing check lets the stop go and stamps the tree');
  bb('edit', 'design', '--check', 'false');
  ok(stop({ stop_hook_active: false }) === '',
     '...and the same tree is not checked again, even though the check would now fail');
}

// ---- reading them from a session -------------------------------------------
ok(/No em dashes/.test(bb('list')) && /agent-compat/.test(bb('list')),
   'bb rules lists what is in effect');
ok(/add, do not change/.test(bb('show', 'agent-compat')),
   'bb rules show reads one in full: how a session follows the name in its block');
// What a session may NOT do is the narrow part, and it is about the whole
// list rather than about writing at all: the tab's replace is a person's,
// because one call rewriting every rule is exactly what the per-rule
// ownership check exists to stop.
let refused = '';
try { execFileSync(BB, ['rules', 'replace'], { env: ENV }); }
catch (e) { refused = String(e.stdout || '') + String(e.stderr || ''); }
ok(/unknown/.test(refused),
   'there is no verb that rewrites the whole list: that one is the tab\'s');

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
ok(/^\* No em dashes/m.test(bb('--prompt')) || /\*dont-edit-during-a-suite/.test(bb('--prompt')),
   'and the block says so too: a session\'s own note must not reach the next one '
   + 'wearing the operator\'s authority');
{
  const h = bb('history');
  // The mark AND the account: "you" and "claude" say a person or a session,
  // and the name says which person, the same thing the Nodes tab's audit
  // has recorded since accounts existed.
  ok(/claude test\s+add\s+dont-edit-during-a-suite/.test(h) && /you test\s+add\s+voice/.test(h),
     'every change is in a history that says who made it, and which account, '
     + 'which is what makes this safe to share, rather than a lock');
}
ok(/dropped dont-edit-during-a-suite/.test(
     bb('rm', 'dont-edit-during-a-suite', 'it belongs in CLAUDE.md now')),
   'a session can drop its own, with the reason kept');

// The endpoint, not just the verb. `bb rules` has no write verb and the file
// tools are denied on the file, but a session has a shell and a token, and
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

// ---- global rules (R63): set once on the controller, in every project -----
// The drift the block has, these do not: there is no copy anywhere, so a rule
// the operator sets is the rule every session on the box is handed.
{
  const auth = { 'Content-Type': 'application/json',
                 Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  const api = async body => {
    const r = await fetch(URL.replace(/\/$/, '') + '/api/global-rules',
      { method: 'POST', headers: auth, body: JSON.stringify(body) });
    return { status: r.status, body: await r.json().catch(() => ({})) };
  };
  const saved = await api({ action: 'save', rules: [
    { name: 'no-secrets', text: 'Never write credentials into a repository.' }] });
  ok(saved.status === 200 && (saved.body.rules || []).some(r => r.name === 'no-secrets'),
     `the operator saves a rule that applies to every project (${saved.status})`);

  const listed = bb();
  ok(/no-secrets/.test(listed) && /\[global\]/.test(listed),
     `a project's rules include the global one, marked (${
       (listed.split('\n').find(l => /no-secrets/.test(l)) || '').trim()})`);
  ok(/no-secrets/.test(bb('--global')) && !/\bmine\b/.test(bb('--global')),
     '`bb rules --global` lists what applies everywhere and nothing project-specific');
  ok(/Never write credentials/.test(bb('--prompt')),
     '...and it is in the standing block every session here is handed');

  let refused = '';
  try { bb('add', '--global', 'sneaky', 'I rule everything'); }
  catch (e) { refused = String(e.stderr) + String(e.stdout); }
  ok(/only the operator adds or changes one/.test(refused),
     `a session cannot add a global rule, and is told who does (${refused.trim().slice(0, 70)})`);

  // A session's token is a principal with user rights over one project; a
  // global rule reaches every project, so this endpoint wants an admin.
  const tok = execFileSync('python3', ['-c', `
import sys; sys.path.insert(0, ${JSON.stringify(join(HERE, '..'))})
import users, statefile
users.configure(write_json=statefile.write_json, state=${JSON.stringify(`${DIR}/state`)})
print(users.mint_session('alpha'))`], { encoding: 'utf8' }).trim();
  const asSession = await fetch(URL.replace(/\/$/, '') + '/api/global-rules',
    { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
      body: JSON.stringify({ action: 'save', rules: [{ name: 'x', text: 'y' }] }) });
  ok(asSession.status === 403, `...and a session's token is refused by the endpoint too (${asSession.status})`);
}

// B195: the tab writes the WHOLE list, so a list that moved since it was loaded
// is somebody else's rule about to be overwritten: one a session added, one an
// administrator approved from the queue, another person's reword. It used to
// go through, and the log then blamed the person saving for removing a rule
// they had never seen.
{
  const call = (path, body) => page.evaluate(async ([p, b]) => {
    const r = await fetch(p, b === null ? {} : { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    return { status: r.status, ...(await r.json().catch(() => ({}))) };
  }, [path, body ?? null]);
  const first = await call('/api/rules?project=alpha');
  const mine = [...(first.rules || []), { name: 'from-tab-one', text: 'a rule written in one window' }];
  const one = await call('/api/rules', { project: 'alpha', action: 'save', rules: mine, rev: first.rev });
  ok(typeof first.rev === 'number' && one.rev !== first.rev
     && (one.rules || []).some(r => r.name === 'from-tab-one'),
     `a save carrying the revision it loaded at goes through, and the revision moves (${first.rev} to ${one.rev})`);
  const theirs = [...(first.rules || []), { name: 'from-tab-two', text: 'written in the other window' }];
  const stale = await call('/api/rules', { project: 'alpha', action: 'save', rules: theirs, rev: first.rev });
  ok(stale.status === 200 && stale.conflict === true
     && (stale.current?.rules || []).some(r => r.name === 'from-tab-one')
     && read().some(r => r.name === 'from-tab-one') && !read().some(r => r.name === 'from-tab-two'),
     'a second window that loaded before that save is told the rules changed, handed what is there now, and writes nothing');
  const forced = await call('/api/rules', { project: 'alpha', action: 'save', rules: theirs,
                                            rev: first.rev, force: true });
  ok(!forced.conflict && read().some(r => r.name === 'from-tab-two') && !read().some(r => r.name === 'from-tab-one'),
     '...and Use mine writes it, which is then a decision somebody made rather than an accident');
  await call('/api/rules', { project: 'alpha', action: 'save', rules: first.rules || [], force: true });
}

// A project's rules beside the global ones. Flat by construction: both lists
// reach a session, and a global rule and a project rule with the same trigger
// both fire. What was missing was everything around that: somebody writing a
// project rule could not see the global ones at all, nothing said which wins,
// and a shared NAME resolved to the global rule, which is backwards. Names
// carry no meaning here on purpose: an override you can only make by knowing
// the other rule's name helps exactly the person who did not need it.
{
  const auth = { 'Content-Type': 'application/json',
                 Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  const post = async (path, body) => (await fetch(URL.replace(/\/$/, '') + path,
    { method: 'POST', headers: auth, body: JSON.stringify(body) })).json();
  const get = async path => (await fetch(URL.replace(/\/$/, '') + path, { headers: auth })).json();
  const gWas = (await get('/api/global-rules')).rules || [];
  await post('/api/global-rules', { action: 'save', rules: [
    ...gWas.filter(r => !r.builtin),
    { name: 'house-changelog', text: 'Every change gets a changelog line.', words: ['changelog'], paths: ['docs'] }] });
  const first = await get('/api/rules?project=alpha');
  await post('/api/rules', { project: 'alpha', action: 'save', force: true, rules: [
    ...(first.rules || []),
    { name: 'our-changelog', text: 'Here the changelog is grouped by component.', words: ['changelog', 'release'], paths: ['docs/guide.md'] },
    { name: 'house-changelog', text: 'A rule that happens to pick a global rule\'s name.' },
    { name: 'unrelated', text: 'Nothing to do with any of it.', words: ['gradle'] }] });
  const got = await get('/api/rules?project=alpha');
  const mine = (got.rules || []).find(r => r.name === 'our-changelog');
  const over = (mine?.overlaps || []).find(o => o.name === 'house-changelog');
  ok((got.global || []).some(g => g.name === 'house-changelog') && over
     && JSON.stringify(over.words) === '["changelog"]' && JSON.stringify(over.paths) === '["docs"]',
     `a project rule is told which global rule fires where it fires, and on what (${JSON.stringify(over)})`);
  ok(((got.rules || []).find(r => r.name === 'unrelated')?.overlaps || []).length === 0,
     '...and one that shares no trigger with any of them is told nothing');
  ok(!(got.rules || []).some(r => r.name === 'house-changelog')
     && (got.rules || []).some(r => r.name === 'house-changelog-2'),
     "a project rule cannot take a global rule's name: it is suffixed, so bb rules show NAME is never ambiguous");
  const told = execFileSync(BB, ['preamble'], { env: ENV }).toString();
  ok(/Where one of this project's rules and a global one disagree, follow the project's, and say so in your reply/.test(told),
     'a session is told which wins where they disagree, since no matching could find a disagreement in meaning');

  // ...and on the page: the global rules are drawn, read-only, and the row says so.
  // A FRESH notebook: the one this file has been driving may be holding
  // staged edits by now, and a panel holding edits does not re-read.
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'notebook'); if (t) hideTab(t.id); });
  await page.evaluate(() => openNotebook('alpha', 'briefing'));
  await page.waitForFunction(() => !!document.querySelector('.pane .nb #rulesBox .rulerow, .pane .nb #rulesBox .grule'),
                             null, { timeout: 20000 });
  let seen = null;
  for (let i = 0; i < 30 && !seen?.global; i++){
    await page.evaluate(() => pollRevs());
    await new Promise(r => setTimeout(r, 400));
    seen = await page.evaluate(() => ({
      global: [...document.querySelectorAll('.nb #rlGlobal .grule .btitle')].map(e => e.textContent).includes('house-changelog'),
      edit: document.querySelectorAll('.nb #rlGlobal .rlEdit, .nb #rlGlobal .rlRm').length,
      pill: [...document.querySelectorAll('.nb #rlList .rulerow')].some(r =>
        r.querySelector('.btitle')?.textContent === 'our-changelog' && /shares ground/.test(r.textContent)) }));
  }
  ok(seen?.global && seen.edit === 0 && seen.pill,
     `the project's Rules list the global ones read-only under its own, and the overlapping row says it shares ground (${JSON.stringify(seen)})`);

  await post('/api/rules', { project: 'alpha', action: 'save', force: true, rules: first.rules || [] });
  await post('/api/global-rules', { action: 'save', rules: gWas.filter(r => !r.builtin) });
}

ok(page.errors.length === 0, `zero console errors${
  page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
await done(browser);
