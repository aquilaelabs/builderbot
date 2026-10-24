// What a session adds to the notebook, held for the operator (roadmap #27).
//
// Per project and per tab the operator picks auto, ask or deny for what a
// session ENTERS, be it a roadmap item, a bug report or a rule. What is exercised
// for real: the three stores through bb (the gate lives in them), the
// settings dialog that sets the words, the band above the notebook's tabs,
// the review modal with its checkboxes and two verbs, the bell's row, the
// hook line that tells the session what was decided, and the endpoint's
// refusal of a session's own token. What is faked: nothing. The hook is the
// shipped script run as a process, and bb is the checkout's.
import { launch, newPage, ok, done, ready, saveDialog, URL, DIR, nbShown, sleep, unfold } from './lib.mjs';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const BB = join(HERE, '..', '..', 'bb');
const ENV = { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
              DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`,
              BB_PROJECT: 'alpha', BB_ROADMAP_PROJECT: 'alpha', BB_BUG_PROJECT: 'alpha' };
const bb = (...a) => execFileSync(BB, a, { env: ENV }).toString();
// The refusal, which bb prints to stderr with a non-zero status.
const bbErr = (...a) => { try { return bb(...a); }
                          catch (e) { return String(e.stdout || '') + String(e.stderr || ''); } };
const file = name => existsSync(`${DIR}/state/${name}`)
  ? JSON.parse(readFileSync(`${DIR}/state/${name}`, 'utf8')) : {};
const roadmapItems = () => file('roadmap.json').projects?.alpha || [];
const bugs = () => file('bugs.json').projects?.alpha || [];
const rulesOf = () => file('rules.json').projects?.alpha?.rules || [];
const waiting = () => file('pending.json').projects?.alpha || [];
const hook = (name, argv, body) => execFileSync(join(HERE, '..', name), argv,
  { env: { ...ENV, BB_TREE: `${DIR}/ws/alpha` }, input: JSON.stringify(body) }).toString();

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
// A hidden element is never "visible", so waiting for `[hidden]` with the
// selector wait never returns: ask the DOM instead.
const gone = sel => page.waitForFunction(q => !!document.querySelector(q)?.hidden, sel,
                                         { timeout: 30000 });
const post = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, [path, body]);

// ---- auto is today ----------------------------------------------------------
const first = bb('roadmap', 'add', 'a thing added under auto');
ok(/added R\d+/.test(first) && roadmapItems().some(r => r.text === 'a thing added under auto'),
   'with nothing set, what a session adds lands at once: the default changes nothing');
const firstId = first.match(/added R(\d+)/)[1];

// ---- the setting, in the project's settings dialog -------------------------
await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
await page.waitForSelector('#rnmodal:not([hidden])');
const opts = await page.$$eval('#rnGateRoadmap option', os => os.map(o => o.value));
ok(opts.join(',') === 'auto,ask,deny'
   && await page.$eval('#rnGateRoadmap', e => e.value) === 'auto'
   && await page.$eval('#rnGateRules', e => e.value) === 'auto'
   && await page.$eval('#rnGateSettings', e => e.value) === 'auto'
   && await page.$eval('#rnGateDesign', e => e.value) === 'auto',
   'the dialog offers auto, ask and deny per tab, for build and test and for the design, and reads auto until something is set');
await page.selectOption('#rnGateRoadmap', 'ask');
await page.selectOption('#rnGateBugs', 'ask');
await page.selectOption('#rnGateRules', 'deny');
await page.selectOption('#rnGateSettings', 'ask');
await saveDialog(page);
const gate = () => file('claude-prefs.json').projects?.alpha?.gate || {};
ok(gate().roadmap === 'ask' && gate().bugs === 'ask' && gate().rules === 'deny' && gate().settings === 'ask',
   'saving writes the four words beside the project\'s other settings');
await page.waitForFunction(() => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.gate?.rules === 'deny',
                           null, { timeout: 30000 });
await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnGateBugs', e => e.value) === 'ask'
   && await page.$eval('#rnGateRules', e => e.value) === 'deny',
   '...and the dialog reads them back next time it opens');
await page.click('#rnCancel');
await gone('#rnmodal');

// ---- ask: held, and the follow-ups ride behind ------------------------------
const held = bb('roadmap', 'add', 'make the picker wrap', '--step', 'measure it');
const num = (held.match(/held for approval as R(\d+)/) || [])[1];
ok(!!num && !roadmapItems().some(r => r.text === 'make the picker wrap'),
   `under ask a session's add is held with a number and is NOT on the list (${held.trim().slice(0, 60)})`);
ok(Number(num) === Number(firstId) + 1,
   '...and the number it is told is the next one, reserved for it');
ok(/held behind R\d+/.test(bb('roadmap', 'info', `R${num}`, 'the details, written early')),
   'details added to a held item ride behind it');
ok(/held behind R\d+/.test(bb('roadmap', 'step', 'add', `R${num}`, 'fix it')),
   '...and so does a step');
ok(/still waiting/.test(bbErr('roadmap', 'done', `R${num}`)),
   '...while ticking it off is refused: there is nothing to tick yet');
ok(/reworded R\d+/.test(bb('roadmap', 'edit', `R${firstId}`, 'a thing added under auto, reworded')),
   'modifying what is already on the list passes under ask: the setting is about creation');
const listed = bb('roadmap', 'pending');
ok(/make the picker wrap/.test(listed) && /↳.*details/.test(listed) && /↳.*fix it/.test(listed)
   && /setting.*ask/.test(listed),
   'bb roadmap pending lists what is waiting, the follow-ups under their item, and the setting');
const second = bb('roadmap', 'add', 'a second held item');
ok(Number((second.match(/R(\d+)/) || [])[1]) === Number(num) + 1,
   'a second held add gets the next number: the reserved one is not handed out twice');

const bheld = bb('bug', 'add', 'the picker loses focus', '--sev', 'high', '--area', 'picker');
const bnum = (bheld.match(/held for approval as B(\d+)/) || [])[1];
ok(!!bnum && !bugs().some(b => b.title === 'the picker loses focus'),
   'a bug report is held the same way');
ok(/held behind B\d+/.test(bb('bug', 'note', `B${bnum}`, 'seen on chrome too')),
   '...a note on it rides behind it');
ok(/still waiting/.test(bbErr('bug', 'fix', `B${bnum}`, 'x')),
   '...and closing it is refused');

// ---- the fourth gate: a session filling in build and test -------------------
const sheld = bb('settings', 'set', 'test', 'echo held-test');
ok(/held for approval: test for alpha/.test(sheld) && !(file('claude-prefs.json').projects?.alpha?.test),
   `under ask a session's bb settings set is held, and the field stays empty (${sheld.trim().slice(0, 60)})`);
ok(waiting().some(r => r.kind === 'settings' && /test: echo held-test/.test(r.summary)),
   '...as a settings change whose summary is the command, since that is what is being approved');

// ---- deny: refused with a sentence to quote ---------------------------------
const refused = bbErr('rules', 'add', 'no-em-dashes', 'No em dashes.');
ok(/setting Agents may: Add rules is deny/.test(refused) && /say it in your reply/.test(refused),
   'under deny the add is refused with a sentence the session can quote');
ok(!waiting().some(r => r.kind === 'rules'),
   '...and nothing is held for it');

// ---- the notebook: the band and the tab counts ------------------------------
await page.evaluate(n => openNotebook(n), 'alpha');
await nbShown(page);
await page.waitForSelector('.pane .nb #nbPending:not([hidden])', { timeout: 20000 });
const band = await page.$eval('.pane .nb #nbPending', e => e.textContent.replace(/\s+/g, ' '));
ok(/7 changes from a session are waiting for your approval/.test(band) && /4 roadmap, 2 bugs, 1 setting/.test(band),
   `the band above the tabs counts what is waiting, per tab (${band.trim().slice(0, 90)})`);
ok(await page.$eval('.pane .nb .nbtabs [data-v="roadmap"] .pcount', e => e.textContent) === '4'
   && await page.$eval('.pane .nb .nbtabs [data-v="bugs"] .pcount', e => e.textContent) === '2'
   && await page.$('.pane .nb .nbtabs [data-v="briefing"] .pcount') === null,
   '...and each tab wears its own count, none where nothing waits');

// ---- the bell --------------------------------------------------------------
await page.waitForFunction(() => !document.querySelector('#bBell .dot').hidden, null, { timeout: 30000 });
ok(await page.$eval('#bBell .dot', d => d.classList.contains('ask')),
   'the bell lights at the ask level: this is waiting on you, not a record of something');
await page.click('#bBell');
await page.waitForSelector('#bellPanel:not([hidden])');
const row = await page.$eval('#bellPanel .bnote.ask', e => e.textContent.replace(/\s+/g, ' '));
ok(/waiting for your approval/.test(row) && /7 changes from a session in alpha/.test(row),
   'the bell carries one row per project, not per change');
await page.click('#bellPanel [data-bpend="alpha"]');
await page.waitForSelector('#pendModal:not([hidden])', { timeout: 10000 });
ok(/alpha/.test(await page.$eval('#pendTitle', e => e.textContent)),
   '...and its Review opens the project\'s list');

// ---- the review modal -------------------------------------------------------
await page.waitForFunction(() => document.querySelectorAll('#pendList .prow').length === 7,
                           null, { timeout: 10000 });
const kinds = await page.$$eval('#pendList .pkind', ks => ks.map(k => k.textContent));
ok(kinds.join(',') === 'Roadmap,Bugs,Build and test',
   'the modal groups what is waiting by tab, and the settings change under its own heading');
ok(await page.$$eval('#pendList input[data-pend]', bs => bs.every(b => b.checked))
   && await page.$eval('#pendAllBox', b => b.checked),
   '...everything ticked, and the master box with it');
ok(await page.$$eval('#pendList .prow.dep', ds => ds.length) === 3,
   '...with the follow-ups drawn under the change they ride behind');
ok(await page.$eval('#pendList .prow:not(.dep) details pre', p => /1\. measure it/.test(p.textContent)),
   '...and the full text of an add (its steps here) under a fold');
// Untick the held roadmap add: its two follow-ups go with it.
const parent = await page.$eval('#pendList .prow:not(.dep) input[data-pend]', b => b.dataset.pend);
await page.click(`#pendList input[data-pend="${parent}"]`);
ok(await page.$$eval('#pendList input[data-pend]:checked', bs => bs.length) === 4
   && await page.$eval('#pendAllBox', b => b.indeterminate),
   'unticking a change unticks what rides behind it, and the master box goes indeterminate');
await page.click('#pendApprove');
await page.waitForFunction(() => document.querySelectorAll('#pendList .prow').length === 3,
                           null, { timeout: 15000 });
ok(file('claude-prefs.json').projects?.alpha?.test === 'echo held-test',
   'Approve replays the settings change: the test command lands in the project\'s settings');
ok(bugs().some(b => b.title === 'the picker loses focus' && /seen on chrome too/.test(b.notes || '')
                    && String(b.id) === bnum && b.by === 'claude')
   && roadmapItems().some(r => r.text === 'a second held item'),
   'Approve replays the ticked ones in order: the report lands with the note that rode behind it, under the number it was told');
ok(!roadmapItems().some(r => r.text === 'make the picker wrap'),
   '...and what was not ticked is still waiting');
ok(/approved by the operator/.test(bb('bug', 'history', '-n', '3')),
   'the tracker\'s log says the filing was approved, not merely that a session filed it');
ok(await page.$$eval('#pendList input[data-pend]', bs => bs.length === 3 && bs.every(b => b.checked)),
   'the modal redraws from the answer with what is left, ticked again');
await page.click('#pendApprove');
await page.waitForSelector('#pendEmpty:not([hidden])', { timeout: 15000 });
const landed = roadmapItems().find(r => r.text === 'make the picker wrap');
ok(!!landed && String(landed.id) === num && landed.info === 'the details, written early'
   && landed.steps.length === 2 && landed.steps[1].text === 'fix it',
   'the roadmap item lands with its details and both steps, under the number it was told');
ok(/approved by the operator/.test(bb('roadmap', 'history', '--find', 'picker wrap')),
   '...and the roadmap\'s log says so');
await page.click('#pendClose');
await gone('#pendModal');
await gone('.pane .nb #nbPending');
ok(await page.$('.pane .nb .nbtabs .pcount') === null,
   'with nothing waiting the band goes and the counts go with it');
await page.waitForFunction(() => document.querySelector('#bBell .dot').hidden
                                 || !document.querySelector('#bBell .dot').classList.contains('ask'),
                           null, { timeout: 30000 });
ok(true, '...and the bell stops asking');

// ---- deny ------------------------------------------------------------------
const dh = bb('roadmap', 'add', 'an item to be denied');
const dnum = (dh.match(/R(\d+)/) || [])[1];
bb('roadmap', 'info', `R${dnum}`, 'details that go with it');
await page.waitForSelector('.pane .nb #nbPending:not([hidden])', { timeout: 30000 });
await page.click('.pane .nb #nbReview');
await page.waitForFunction(() => document.querySelectorAll('#pendList .prow').length === 2,
                           null, { timeout: 10000 });
await page.click('#pendDeny');
await page.waitForSelector('#pendEmpty:not([hidden])', { timeout: 15000 });
ok(!roadmapItems().some(r => r.text === 'an item to be denied') && waiting().length === 0,
   'Deny drops the change and what rode behind it, and nothing lands');
ok(/denied/.test(bb('history', '--find', 'to be denied')),
   '...and the merged log records the denial under "waiting"');
await page.click('#pendClose');
const after = bb('roadmap', 'add', 'added after the denial');
ok(Number((after.match(/R(\d+)/) || [])[1]) > Number(dnum),
   'a denied number is a gap, never reused');

// ---- the session is told --------------------------------------------------
const told = hook('bb-prompt-relay', ['alpha', 'u_test'], { prompt: 'what next' });
ok(/The operator has answered/.test(told) && /make the picker wrap.*approved/.test(told)
   && /to be denied.*denied/.test(told),
   `the next prompt tells the session what was approved and what was denied (${told.replace(/\s+/g, ' ').slice(0, 120)})`);
ok(!/The operator has answered/.test(hook('bb-prompt-relay', ['alpha', 'u_test'], { prompt: 'and' })),
   '...once');

// ---- a session cannot answer for itself -------------------------------------
{
  const tok = execFileSync('python3', ['-c', `
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('users', ${JSON.stringify(join(HERE, '..', 'users.py'))})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import json
def wj(path, d):
    tmp = str(path) + '.new'
    with open(tmp, 'w') as f: json.dump(d, f, indent=2)
    os.replace(tmp, path)
m.configure(state=${JSON.stringify(`${DIR}/state`)}, write_json=wj)
print(m.mint_session('alpha'))
`], { encoding: 'utf8' }).trim();
  const res = await fetch(URL.replace(/\/$/, '') + '/api/pending', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
    body: JSON.stringify({ project: 'alpha', action: 'approve', ids: [1, 2, 3] }) });
  const body = await res.text();
  ok(res.status === 403 && /cannot answer for itself/.test(body),
     `a session's own token cannot approve what it added (${res.status} ${body.slice(0, 80)})`);
}

// ---- rules, through the same door ------------------------------------------
const set = await post('/api/prefs', { project: 'alpha', gate: { rules: 'ask' } });
ok(set.status === 200 && set.body.gate?.rules === 'ask' && set.body.gate?.roadmap === 'ask',
   'the endpoint takes one word at a time and leaves the others as they were');
const rh = bb('rules', 'add', 'no-em-dashes', 'No em dashes.');
ok(/held for approval as the rule no-em-dashes/.test(rh) && !rulesOf().some(r => r.name === 'no-em-dashes'),
   'a rule is held by name');
ok(/held behind the rule no-em-dashes/.test(bb('rules', 'edit', 'no-em-dashes', 'No em dashes, ever.')),
   '...a rewording rides behind it');
const ap = await post('/api/pending', { project: 'alpha', action: 'approve',
                                        ids: waiting().filter(r => r.kind === 'rules').map(r => r.id) });
ok(ap.status === 200 && ap.body.approved?.length === 2
   && rulesOf().some(r => r.name === 'no-em-dashes' && r.text === 'No em dashes, ever.' && r.by === 'claude'),
   `approved, the rule lands with the final wording, marked as the session's (${ap.status} ${JSON.stringify(ap.body).slice(0, 200)} / ${JSON.stringify(rulesOf()).slice(0, 200)})`);
ok(/no rule is waiting/.test(bb('rules', 'pending')),
   'and bb rules pending says so');

await done(browser);// A session asking for an item back off the shelf (R78) is held whatever the
// gate says, with its reason, and a person's Approve replays it: a decision
// with a notification behind it, not a gate on creation.
{
  const added = await post('/api/roadmap', { project: 'alpha', action: 'add', text: 'a parked plan' });
  const id = added.body.item.id;
  bb('roadmap', 'shelve', String(id));
  const asked = bb('roadmap', 'unshelve', String(id), 'the blocker is gone');
  ok(/asked to take R\d+ off the shelf: held for approval/.test(asked) && !!roadmapItems().find(r => r.id === id)?.shelved,
     `a session asking to unshelve is held, and the item stays shelved meanwhile (${asked.trim().slice(0, 60)}…)`);
  const rec = waiting().find(r => r.verb === 'unshelve');
  ok(!!rec && rec.number === id && /take R\d+ off the shelf: the blocker is gone/.test(rec.summary),
     `...as a pending record carrying the reason (${rec?.summary})`);
  const ap = await post('/api/pending', { project: 'alpha', action: 'approve', ids: [rec.id] });
  ok(ap.status === 200 && (ap.body.approved || []).length === 1 && !roadmapItems().find(r => r.id === id)?.shelved,
     `the operator's Approve takes it off the shelf (${JSON.stringify(ap.body).slice(0, 80)})`);
  bb('roadmap', 'done', String(id));
  ok(!roadmapItems().some(r => r.id === id),
     '...and the request never locked the item: a session ticks it off as usual afterwards');
}


