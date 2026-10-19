// The Profile's conversation logs: an account's own transcripts, listed
// newest first with the first thing typed, and each downloadable as a text
// that carries the words, every command Claude ran and what came back, and
// never Claude's private reasoning nor another account's file.
import { URL, launch, newPage, ok, done, ready, DIR, splitPick } from './lib.mjs';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
const slug = p => p.replace(/\//g, '-');
const line = o => JSON.stringify(o) + '\n';
const msg = (type, content, extra = {}) => ({ type, timestamp: '2026-09-28T10:15:00.000Z',
  message: { role: type, content }, ...extra });
const tree = join(DIR, 'home', '.claude', 'projects', slug(join(DIR, 'ws', 'alpha')));
mkdirSync(tree, { recursive: true });
writeFileSync(join(tree, 'conv-one-2026.jsonl'), [
  line({ type: 'summary', summary: 'not a turn' }),
  line(msg('user', 'Please tick the roadmap item off for me')),
  line(msg('assistant', [{ type: 'thinking', thinking: 'SECRET REASONING' },
    { type: 'text', text: 'Reading the roadmap first.' },
    { type: 'tool_use', id: 't1', name: 'Bash', input: { command: 'bb roadmap show R4', description: 'Read item four' } }])),
  line(msg('user', [{ type: 'tool_result', tool_use_id: 't1', content: 'R4  The thing to do\n  1. a step' }])),
  line(msg('assistant', [{ type: 'tool_use', id: 't2', name: 'Read', input: { file_path: '/workspace/alpha/README.md' } }])),
  line(msg('user', [{ type: 'tool_result', tool_use_id: 't2', content: [{ type: 'text', text: 'hello readme' }], is_error: true }])),
  line(msg('user', 'SIDECHAIN WORDS', { isSidechain: true })),
  line(msg('user', 'Stop hook feedback: a check failed', { isMeta: true })),
  line(msg('assistant', [{ type: 'text', text: 'Done: R4 is ticked.' }])),
].join(''));
// An older one from a worktree session, listed after the newer.
const wt = join(DIR, 'home', '.claude', 'projects', slug(join(DIR, 'ws', '.worktrees', 'alpha', uid)));
mkdirSync(wt, { recursive: true });
writeFileSync(join(wt, 'conv-two-2025.jsonl'), line(msg('user', 'An earlier chat from the worktree')));
const old = new Date('2025-01-01T00:00:00Z');
const { utimesSync } = await import('node:fs');
utimesSync(join(wt, 'conv-two-2025.jsonl'), old, old);

// The stamps are the controller's local time; the server runs on this box.
const local = t => { const d = new Date(t), p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
const AT = local('2026-09-28T10:15:00.000Z');
const ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
const browser = await launch();
const page = await newPage(browser);
await page.goto(URL); await ready(page);
await page.evaluate(() => openProfileTab());
// Profile is a page of settings: its logs are a section picked from its list.
await page.waitForSelector('.profiletab .snav [data-spick="logs"]', { timeout: 15000 });
await splitPick(page, 'logs');
await page.waitForSelector('.profiletab .cvlogs .artrow', { timeout: 15000 });
const rows = await page.$$eval('.profiletab .cvlogs .artrow', els => els.map(e => ({
  text: e.textContent.replace(/\s+/g, ' ').trim(), href: e.querySelector('a.btn')?.getAttribute('href') || '' })));
ok(rows.length >= 2, `the Profile lists the account's conversations (${rows.length})`);
ok(/^alpha .*Please tick the roadmap item off/.test(rows[0].text), `the newest first, with the first thing typed: ${rows[0].text.slice(0, 70)}`);
ok(rows[0].href === `/api/transcript?project=alpha&id=conv-one-2026&tz=${encodeURIComponent(ZONE)}`, `its Download is the transcript by project and id, in this browser's zone: ${rows[0].href}`);
ok(rows.some(r => /An earlier chat from the worktree/.test(r.text)), 'a worktree session of the same project is listed with it');
const i1 = rows.findIndex(r => /conv-one-2026/.test(r.href)), i2 = rows.findIndex(r => /conv-two-2025/.test(r.href));
ok(i1 >= 0 && i2 > i1, 'newest first');
ok(await page.$eval('.profiletab .cvlogs .artrow a.btn', a => a.hasAttribute('download') && a.getBoundingClientRect().height >= 30),
  'the download is a link dressed as a button, a tap tall');
ok(await page.$$eval('.profiletab .cvlogs .artrow', els => els.length > 1 && els.slice(0, -1).every(e => getComputedStyle(e).borderBottomWidth === '1px')),
  "the rows are the Artifacts view's: a hairline between each");

const got = await page.evaluate(async href => {
  const r = await fetch(href);
  return { status: r.status, type: r.headers.get('content-type'), disp: r.headers.get('content-disposition'), text: await r.text() };
}, rows[0].href);
ok(got.status === 200 && /^text\/plain/.test(got.type), `the download is plain text (${got.status} ${got.type})`);
ok(/attachment; filename="claude-alpha-\d{8}-\d{4}-conv-one.txt"/.test(got.disp), `named for the project, the time and the session: ${got.disp}`);
ok(/^Conversation on alpha, session conv-one-2026/.test(got.text), 'headed with the project and the session');
ok(got.text.includes(`You (${AT}):\nPlease tick the roadmap item off for me`), `what you said, stamped in local time (${AT})`);
ok(got.text.includes(`Claude (${AT}):\nReading the roadmap first.`), 'what Claude said');
ok(/\$ bb roadmap show R4\n  \(Read item four\)/.test(got.text), 'a shell command as typed, with what it was for');
ok(/Result:\nR4  The thing to do\n  1\. a step/.test(got.text), 'and what bb answered, whole');
ok(/Read: \/workspace\/alpha\/README\.md\nResult \(error\):\nhello readme/.test(got.text), 'a file read by its path, and a failed result marked');
ok(got.text.includes(`Claude (${AT}):\nDone: R4 is ticked.`), 'the closing words');
ok(got.text.includes(`System (${AT}):\nStop hook feedback: a check failed`), 'what a hook put in front of Claude is headed System, not You');
ok(!/SECRET REASONING/.test(got.text), "Claude's private reasoning is not in it");
ok(!/SIDECHAIN WORDS/.test(got.text), 'a subagent side chain is not in it');
ok(!/not a turn/.test(got.text), 'a summary line is not in it');

const tokyo = await page.evaluate(async () => (await fetch('/api/transcript?project=alpha&id=conv-one-2026&tz=Asia/Tokyo')).text());
ok(/You \(2026-09-28 19:15\):/.test(tokyo), 'the stamps follow the zone the link names');
const nozone = await page.evaluate(async () => (await fetch('/api/transcript?project=alpha&id=conv-one-2026&tz=Mars%2FOlympus')).status);
ok(nozone === 200, `a zone that is not one falls back to the controller's own (${nozone})`);
const miss = await page.evaluate(async () => (await fetch('/api/transcript?project=alpha&id=nope')).status);
ok(miss === 404, `an id the account has no transcript for is not found (${miss})`);
const bad = await page.evaluate(async () => (await fetch('/api/transcript?project=alpha&id=..%2F..%2Fconv-one-2026')).status);
ok(bad === 404, `a path in the id is not found either (${bad})`);
const none = await page.evaluate(async () => (await fetch('/api/transcript?project=nosuch&id=conv-one-2026')).status);
ok(none === 400, `a project that is not one is refused as not a project (${none})`);

// ---- a session reads its account's own conversations, on its project and on a read ----
// The operator's ask (29 Sep): a session on alpha, with beta among alpha's
// reads, reads the account's conversations on beta, through bb transcripts;
// a project alpha does not read is not a project to it, and nothing of
// another account's is ever found.
const { execFileSync } = await import('node:child_process');
const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const betaTree = join(DIR, 'home', '.claude', 'projects', slug(join(DIR, 'ws', 'beta')));
mkdirSync(betaTree, { recursive: true });
writeFileSync(join(betaTree, 'beta-chat-1.jsonl'), line(msg('user', 'Make the beta page blue')) + line(msg('assistant', [{ type: 'text', text: 'Blue it is.' }])));
const token = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'], { encoding: 'utf8',
  env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const asSession = { headers: { Authorization: 'Bearer ' + token } };
const sfetch = (path, opts = {}) => fetch(URL.replace(/\/$/, '') + path, { ...opts, headers: { ...(opts.headers || {}), ...asSession.headers } });
await page.evaluate(async () => { await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project: 'alpha', reads: ['beta'] }) }); });
const own = await (await sfetch('/api/transcripts?project=alpha')).json();
ok(own.rows?.some(r => r.id === 'conv-one-2026'), `a session lists the account's conversations on its own project (${(own.rows || []).length})`);
const onRead = await (await sfetch('/api/transcripts?project=beta')).json();
ok(onRead.rows?.length === 1 && onRead.rows[0].id === 'beta-chat-1' && /Make the beta page blue/.test(onRead.rows[0].first),
   `...and on a project its own reads (${JSON.stringify(onRead.rows?.[0] || onRead)})`);
const readText = await sfetch('/api/transcript?project=beta&id=beta-chat-1&as=json');
const rj = await readText.json();
ok(readText.status === 200 && /You \(.*\):\nMake the beta page blue/.test(rj.text) && /Claude \(.*\):\nBlue it is\./.test(rj.text),
   'and reads one there as text, the same text the Profile downloads');
const notRead = await sfetch('/api/transcripts?project=delta');
ok(notRead.status === 400, `a project alpha does not read is not a project to the session (${notRead.status})`);
const cli = (...a) => execFileSync('bash', [`${REPO}/scripts/bb`, ...a], { encoding: 'utf8',
  env: { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''), BB_TOKEN: token, BB_PROJECT: 'alpha', XDG_CACHE_HOME: `${DIR}/cache-transcripts` } });
const listed = cli('-p', 'beta', 'transcripts');
ok(/^your conversations with Claude on beta, newest first:\n  beta-chat-1  /.test(listed) && /Make the beta page blue/.test(listed),
   `bb -p NAME transcripts lists the account's conversations on a read project (${listed.split('\n')[1]?.trim()})`);
const shown = cli('-p', 'beta', 'transcripts', 'show', 'beta-chat-1', '--tz', 'Asia/Tokyo');
ok(/^Conversation on beta, session beta-chat-1/.test(shown) && /You \(2026-09-28 19:15\):\nMake the beta page blue/.test(shown),
   'bb transcripts show ID prints one, stamped in the zone asked for');
ok(/^your conversations with Claude on alpha/.test(cli('transcripts', 'list')), 'and with no -p it is the session\'s own project');
await page.evaluate(async () => { await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project: 'alpha', reads: [] }) }); });
await page.close();
await done(browser);
