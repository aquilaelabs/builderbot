// A new project's brief (brief.py): what New project was told to build, kept
// out of CLAUDE.md, where every session would read it as standing
// instructions, and handed to the FIRST session instead. The first Claude
// press opens a dialog with the brief to change and the model and effort
// that session starts on; Build it stages the brief and the session takes it
// as it starts, which is when it leaves the tree; Start without it puts it
// away unsent. The notebook's Briefing view keeps it either way.
//
// Through startClaude, the entry the Claude button reaches once a node is
// settled: a project made here has no node, and pressing Claude on one of
// those says so before anything else, which is cards.mjs's to hold.
import { launch, newPage, ok, done, ready, URL, DIR, refreshUntil } from './lib.mjs';
import { existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const base = URL.replace(/\/$/, '');
const BRIEF = 'Build a planner for armor stats.\n\n- one page\n- "quotes" and $HOME stay as typed';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

const api = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, b ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify(b) } : {});
  return { status: r.status, ...(await r.json()) };
}, [path, body]);
const made = await api('/api/create', { name: 'briefly', mode: 'init', about: BRIEF, version: '' });
const made2 = await api('/api/create', { name: 'briefless', mode: 'init', about: 'set this aside', version: '' });
ok(made.ok && made2.ok, `two projects made with a brief (${made.error || made2.error || 'ok'})`);
await refreshUntil(page, () => state?.projects?.find(p => p.name === 'briefless')?.brief === true, { timeout: 20000 });
const tabsFor = name => page.evaluate(n => tabs.filter(t => t.kind === 'term' && t.arg.startsWith('claude:' + n)).length, name);

// ---- the first press opens the brief, not a session --------------------------
await page.evaluate(() => startClaude('briefly', null, ''));
await page.waitForSelector('#briefModal:not([hidden])', { timeout: 10000 });
await page.waitForFunction(() => document.getElementById('briefText').value.length > 0, null, { timeout: 10000 });
const shown = await page.evaluate(() => ({
  title: document.getElementById('briefTitle').textContent,
  text: document.getElementById('briefText').value,
  models: [...document.querySelectorAll('#briefModel option')].map(o => o.value),
  efforts: [...document.querySelectorAll('#briefEffort option')].map(o => o.value) }));
ok(/briefly/.test(shown.title) && shown.text === BRIEF.trim()
   && shown.models.includes('haiku') && shown.efforts.includes('low') && await tabsFor('briefly') === 0,
   `the first Claude press opens the brief to change, with the model and effort, and no session yet (${
      shown.title}; ${shown.models.length} models, ${shown.efforts.length} efforts)`);
await page.keyboard.press('Escape');
await page.waitForSelector('#briefModal', { state: 'hidden', timeout: 5000 });
ok(await tabsFor('briefly') === 0 && (await api('/api/brief?project=briefly')).pending,
   '...and Escape puts it away with nothing started and the brief still waiting');

// ---- Build it -----------------------------------------------------------------
await page.evaluate(() => startClaude('briefly', null, ''));
await page.waitForSelector('#briefModal:not([hidden])', { timeout: 10000 });
await page.waitForFunction(() => !document.getElementById('briefGo').disabled, null, { timeout: 10000 });
await page.fill('#briefText', '');
await page.click('#briefGo');
await page.waitForFunction(() => !document.getElementById('briefErrWrap').hidden, null, { timeout: 10000 });
ok(/the brief is empty/.test(await page.$eval('#briefErr', e => e.textContent)) && await tabsFor('briefly') === 0,
   'an empty brief is not built from, and says Start without it is the way to start with none');
const EDITED = BRIEF + '\n\nAdded in the dialog.';
await page.fill('#briefText', EDITED);
await page.selectOption('#briefModel', 'haiku');
await page.selectOption('#briefEffort', 'low');
await page.click('#briefGo');
await page.waitForSelector('#briefModal', { state: 'hidden', timeout: 10000 });
await page.waitForFunction(() => tabs.some(t => t.kind === 'term' && t.arg.startsWith('claude:briefly')), null, { timeout: 10000 });
const staged = await api('/api/brief?project=briefly');
await refreshUntil(page, () => state?.projects?.find(p => p.name === 'briefly')?.yours?.model === 'haiku', { timeout: 20000 });
ok(staged.pending && staged.staged && staged.text === EDITED.trim()
   && await page.evaluate(() => state.projects.find(p => p.name === 'briefly').yours.effort) === 'low',
   'Build it saves the model and effort, stages the brief as edited for this account, and opens the session');

// ---- the session takes it as it starts ----------------------------------------
// What bb-tty does for a new session, as the session: its token, its project.
const token = project => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', project, 'test'],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const tok = token('briefly');
const asSession = async body => (await fetch(base + '/api/brief', { method: 'POST',
  headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
const refused = await asSession({ action: 'stage', project: 'briefly', text: 'a session rewriting it' });
ok(/dialog is a person's/.test(refused.error || ''), `a session cannot stage a brief itself (${refused.error})`);
const took = await asSession({ action: 'take', project: 'briefly' });
const after = await api('/api/brief?project=briefly');
ok(took.text === EDITED.trim() && !existsSync(`${DIR}/ws/briefly/BUILDERBOT-BRIEF.md`)
   && !after.pending && after.kept?.sent === true && after.kept.text === EDITED.trim() && after.kept.by === 'test',
   `the session's take is the brief as edited, which leaves the tree then and is kept as sent (${JSON.stringify(after.kept).slice(0, 80)})`);
ok((await asSession({ action: 'take', project: 'briefly' })).text === '',
   '...and only once: the next session takes nothing');
// bb brief, the verb a session reads it back with.
const said = execFileSync('bash', [`${REPO}/scripts/bb`, 'brief'], { encoding: 'utf8',
  env: { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: base, BB_TOKEN: tok, BB_PROJECT: 'briefly',
         XDG_CACHE_HOME: `${DIR}/cache-brief` } });
ok(/was started from this brief, sent to the first session/.test(said) && said.includes('Added in the dialog.'),
   `bb brief prints the brief the project was started from (${said.split('\n')[0].slice(0, 80)})`);
await refreshUntil(page, () => state?.projects?.find(p => p.name === 'briefly')?.brief === false, { timeout: 20000 });
await page.evaluate(() => { tabs.filter(t => t.arg?.startsWith('claude:briefly')).forEach(t => dropTab(t.id)); });
await page.evaluate(() => startClaude('briefly', null, ''));
await page.waitForFunction(() => tabs.some(t => t.kind === 'term' && t.arg.startsWith('claude:briefly')), null, { timeout: 10000 });
ok(await page.$eval('#briefModal', e => e.hidden), 'once the brief has left, Claude starts a session with no dialog');

// ---- Start without it -------------------------------------------------------------
await page.evaluate(() => startClaude('briefless', null, ''));
await page.waitForSelector('#briefModal:not([hidden])', { timeout: 10000 });
await page.waitForFunction(() => !document.getElementById('briefSkip').disabled, null, { timeout: 10000 });
await page.click('#briefSkip');
await page.waitForSelector('#briefModal', { state: 'hidden', timeout: 10000 });
await page.waitForFunction(() => tabs.some(t => t.kind === 'term' && t.arg.startsWith('claude:briefless')), null, { timeout: 10000 });
const aside = await api('/api/brief?project=briefless');
ok(!aside.pending && aside.kept?.sent === false && aside.kept.text === 'set this aside'
   && !existsSync(`${DIR}/ws/briefless/BUILDERBOT-BRIEF.md`),
   'Start without it opens a session and puts the brief away unsent, kept outside the tree');

// ---- another agent's first session takes it the same way (R95) ------------------
// A new Codex conversation on a project with a brief waiting opens the same
// dialog, with Codex's own models, and Build it opens Codex's session.
const made3 = await api('/api/create', { name: 'briefcodex', mode: 'init', about: 'Build a minesweeper.', version: '' });
await refreshUntil(page, () => state?.projects?.find(p => p.name === 'briefcodex')?.brief === true, { timeout: 20000 });
await page.evaluate(() => openBrief('briefcodex', '', 'codex'));
await page.waitForFunction(() => !document.getElementById('briefGo').disabled
  && document.getElementById('briefText').value.length > 0, null, { timeout: 10000 });
const cx = await page.evaluate(() => ({ title: document.getElementById('briefTitle').textContent,
  models: [...document.querySelectorAll('#briefModel option')].map(o => o.value) }));
ok(made3.ok && /Codex|ChatGPT/.test(cx.title) && cx.models[0] === '' && !cx.models.includes('haiku') && cx.models.length > 1,
   `a Codex first session opens the brief with Codex's own models (${cx.title}; ${cx.models.join(',')})`);
await page.selectOption('#briefModel', cx.models[1]);
await page.click('#briefGo');
await page.waitForSelector('#briefModal', { state: 'hidden', timeout: 10000 });
await page.waitForFunction(() => tabs.some(t => t.kind === 'term' && t.arg.startsWith(agentArg('codex', 'briefcodex'))), null, { timeout: 10000 });
const cxStaged = await api('/api/brief?project=briefcodex');
await refreshUntil(page, `state?.projects?.find(p => p.name === 'briefcodex')?.yours?.codex_model === ${JSON.stringify(cx.models[1])}`, { timeout: 20000 }).catch(() => {});
ok(cxStaged.staged && cxStaged.text === 'Build a minesweeper.'
   && await page.evaluate(() => state.projects.find(p => p.name === 'briefcodex').yours?.codex_model) === cx.models[1]
   && await tabsFor('briefcodex') === 0,
   `...and Build it stages the brief, saves Codex's model, and opens a Codex session, not Claude's (${cxStaged.error || 'staged'})`);

// ---- the notebook keeps it --------------------------------------------------------
await page.evaluate(() => openNotebook('briefly', 'briefing'));
await page.waitForFunction(() => /Sent as the first session's first prompt/.test(
  document.querySelector('.pane .nb [data-sect="briefing:brief"]')?.textContent || ''), null, { timeout: 20000 });
const kept = await page.evaluate(() => {
  const s = document.querySelector('.pane .nb [data-sect="briefing:brief"]');
  return { status: s.querySelector('summary .sst')?.textContent, text: s.querySelector('#briefKept')?.value };
});
ok(kept.status === 'sent' && kept.text === EDITED.trim(),
   `the notebook's Briefing view keeps the brief, saying it was sent (${kept.status})`);

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
