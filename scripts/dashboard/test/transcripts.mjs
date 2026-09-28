// The Profile's conversation logs: an account's own transcripts, listed
// newest first with the first thing typed, and each downloadable as a text
// that carries the words, every command Claude ran and what came back, and
// never Claude's private reasoning nor another account's file.
import { URL, launch, newPage, ok, done, ready, DIR } from './lib.mjs';
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
  line(msg('assistant', [{ type: 'text', text: 'Done: R4 is ticked.' }])),
].join(''));
// An older one from a worktree session, listed after the newer.
const wt = join(DIR, 'home', '.claude', 'projects', slug(join(DIR, 'ws', '.worktrees', 'alpha', uid)));
mkdirSync(wt, { recursive: true });
writeFileSync(join(wt, 'conv-two-2025.jsonl'), line(msg('user', 'An earlier chat from the worktree')));
const old = new Date('2025-01-01T00:00:00Z');
const { utimesSync } = await import('node:fs');
utimesSync(join(wt, 'conv-two-2025.jsonl'), old, old);

const browser = await launch();
const page = await newPage(browser);
await page.goto(URL); await ready(page);
await page.evaluate(() => openProfileTab());
await page.waitForSelector('.profiletab .cvlog', { timeout: 15000 });
const rows = await page.$$eval('.profiletab .cvlog', els => els.map(e => ({
  text: e.textContent.replace(/\s+/g, ' ').trim(), href: e.querySelector('a.btnish')?.getAttribute('href') || '' })));
ok(rows.length >= 2, `the Profile lists the account's conversations (${rows.length})`);
ok(/^alpha .*Please tick the roadmap item off/.test(rows[0].text), `the newest first, with the first thing typed: ${rows[0].text.slice(0, 70)}`);
ok(rows[0].href === '/api/transcript?project=alpha&id=conv-one-2026', `its Download is the transcript by project and id: ${rows[0].href}`);
ok(rows.some(r => /An earlier chat from the worktree/.test(r.text)), 'a worktree session of the same project is listed with it');
const i1 = rows.findIndex(r => /conv-one-2026/.test(r.href)), i2 = rows.findIndex(r => /conv-two-2025/.test(r.href));
ok(i1 >= 0 && i2 > i1, 'newest first');
ok(await page.$eval('.profiletab .cvlog a.btnish', a => a.hasAttribute('download') && a.getBoundingClientRect().height >= 30),
  'the download is a link dressed as a button, a tap tall');

const got = await page.evaluate(async href => {
  const r = await fetch(href);
  return { status: r.status, type: r.headers.get('content-type'), disp: r.headers.get('content-disposition'), text: await r.text() };
}, rows[0].href);
ok(got.status === 200 && /^text\/plain/.test(got.type), `the download is plain text (${got.status} ${got.type})`);
ok(/attachment; filename="claude-alpha-\d{8}-\d{4}-conv-one.txt"/.test(got.disp), `named for the project, the time and the session: ${got.disp}`);
ok(/^Conversation on alpha, session conv-one-2026/.test(got.text), 'headed with the project and the session');
ok(/You \(2026-09-28 10:15\):\nPlease tick the roadmap item off for me/.test(got.text), 'what you said, stamped');
ok(/Claude \(2026-09-28 10:15\):\nReading the roadmap first\./.test(got.text), 'what Claude said');
ok(/\$ bb roadmap show R4\n  \(Read item four\)/.test(got.text), 'a shell command as typed, with what it was for');
ok(/Result:\nR4  The thing to do\n  1\. a step/.test(got.text), 'and what bb answered, whole');
ok(/Read: \/workspace\/alpha\/README\.md\nResult \(error\):\nhello readme/.test(got.text), 'a file read by its path, and a failed result marked');
ok(/Claude \(2026-09-28 10:15\):\nDone: R4 is ticked\./.test(got.text), 'the closing words');
ok(!/SECRET REASONING/.test(got.text), "Claude's private reasoning is not in it");
ok(!/SIDECHAIN WORDS/.test(got.text), 'a subagent side chain is not in it');
ok(!/not a turn/.test(got.text), 'a summary line is not in it');

const miss = await page.evaluate(async () => (await fetch('/api/transcript?project=alpha&id=nope')).status);
ok(miss === 404, `an id the account has no transcript for is not found (${miss})`);
const bad = await page.evaluate(async () => (await fetch('/api/transcript?project=alpha&id=..%2F..%2Fconv-one-2026')).status);
ok(bad === 404, `a path in the id is not found either (${bad})`);
const none = await page.evaluate(async () => (await fetch('/api/transcript?project=nosuch&id=conv-one-2026')).status);
ok(none === 400, `a project that is not one is refused as not a project (${none})`);
await page.close();
await done(browser);
