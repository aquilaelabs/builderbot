// Many people and many Claude sessions writing one project's notebook at the
// same moment. Every session's `bb roadmap`, `bb bug` and `bb changelog` is
// relayed to the controller and run there as a process of its own, so six
// sessions typing at once are six processes on one set of files, beside the
// dashboard's own writes from somebody at the Roadmap tab. Nothing written
// may be lost or written twice, numbers must stay unique, and the files must
// never be seen half-written. No browser: the relay and the API are what a
// session and the panel use.
import { ok, done, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import http from 'node:http';
import { join } from 'node:path';

const HERE = new globalThis.URL('..', import.meta.url).pathname;
const ADMIN = 'Basic ' + Buffer.from('test:test').toString('base64');
// node:http rather than fetch: see robust.mjs for the assertion inside
// Node's fetch that a closing HTTP/1.0 server trips.
const req = (method, path, body, auth = ADMIN) => new Promise((resolve, reject) => {
  const u = new globalThis.URL(URL.replace(/\/$/, '') + path);
  const data = body === undefined ? null : Buffer.from(JSON.stringify(body));
  const r = http.request({ host: u.hostname, port: u.port, path: u.pathname + u.search, method,
    headers: { Authorization: auth, ...(data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {}) } },
  res => { const c = []; res.on('data', x => c.push(x)); res.on('end', () => {
    const t = Buffer.concat(c).toString('utf8');
    let j; try { j = JSON.parse(t); } catch { j = { raw: t }; }
    resolve({ status: res.statusCode, ...j }); }); });
  r.on('error', reject);
  if (data) r.write(data);
  r.end();
});
const usersPy = code => execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", ${JSON.stringify(join(HERE, 'users.py'))})
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state=${JSON.stringify(join(DIR, 'state'))}, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
${code}`], { encoding: 'utf8' }).trim().split('\n').pop();

// Four people on alpha: the owner, an administrator and two plain users.
const make = (name, role) => usersPy(`
d = u.load(); uid = u.mint_uid()
d["users"]["${name}"] = {"uid": uid, "role": "${role}", "projects": ["alpha"],
    "prefs": {"full_name": "${name}", "email": "${name}@example.invalid"},
    "password": u.hash_password("pw-${name}-1"), "created": 0, "seen": 0}
u._save(d); print(uid)`);
const owner = usersPy('print(next(r["uid"] for r in u.load()["users"].values() if r.get("role") == "owner"))');
const people = { owner, admin: make('cc.admin', 'admin'), user1: make('cc.user1', 'user'), user2: make('cc.user2', 'user') };
const tok = uid => usersPy(`print(u.mint_session("alpha", uid=${JSON.stringify(uid)}))`);
// Six sessions: one each, and two more conversations for two of them.
const sessions = [
  ['owner', tok(people.owner)], ['admin', tok(people.admin)], ['user1', tok(people.user1)],
  ['user2', tok(people.user2)], ['user1b', tok(people.user1)], ['ownerb', tok(people.owner)],
];
const relay = (t, argv) => req('POST', '/api/v1/bb', { argv, cwd: `${DIR}/ws/alpha` }, 'Bearer ' + t);

// The roadmap holds at most 30 open items (it goes in front of every session),
// so its share stays under that with the fixture's own; bugs and the
// changelog take more, the changelog most, since it is the one a race shows in.
const ROUNDS = 6, ROADMAP = 3, CHANGES = 12;
const jobs = [];
for (const [who, t] of sessions) {
  for (let i = 0; i < ROADMAP; i++)
    jobs.push(relay(t, ['roadmap', 'add', `cc ${who} item ${i}`]).then(r => ({ who, kind: 'roadmap', i, r })));
  for (let i = 0; i < ROUNDS; i++)
    jobs.push(relay(t, ['bug', 'add', `cc ${who} bug ${i}`, '--sev', 'low']).then(r => ({ who, kind: 'bug', i, r })));
  for (let i = 0; i < CHANGES; i++)
    jobs.push(relay(t, ['changelog', 'add', `cc ${who} change ${i}`, '--cat', 'Changed']).then(r => ({ who, kind: 'changelog', i, r })));
}
// ...and somebody at the Roadmap tab, adding through the panel meanwhile.
for (let i = 0; i < ROADMAP; i++)
  jobs.push(req('POST', '/api/roadmap', { project: 'alpha', action: 'add', text: `cc panel item ${i}` })
    .then(r => ({ who: 'panel', kind: 'roadmap', i, r })));
const t0 = Date.now();
const results = await Promise.all(jobs);
const failed = results.filter(x => x.r.status !== 200 || (x.r.code !== undefined && x.r.code !== 0) || x.r.error);
ok(failed.length === 0,
   `${results.length} writes from ${sessions.length} sessions and the panel at once all answered (${
     failed.length ? failed.slice(0, 3).map(x => `${x.who} ${x.kind}: ${(x.r.error || x.r.out || x.r.raw || '').trim().slice(0, 60)}`).join(' | ') : `${Date.now() - t0}ms`})`);

// The roadmap: every item exactly once, numbers unique.
const roadmap = await req('GET', '/api/roadmap?project=alpha');
const items = JSON.stringify(roadmap);
const want = [...sessions.flatMap(([who]) => [...Array(ROADMAP).keys()].map(i => `cc ${who} item ${i}`)),
              ...[...Array(ROADMAP).keys()].map(i => `cc panel item ${i}`)];
const count = s => items.split(JSON.stringify(s).slice(1, -1)).length - 1;
const lost = want.filter(s => count(s) === 0), twice = want.filter(s => count(s) > 1);
ok(!lost.length && !twice.length,
   `every roadmap item landed exactly once (${want.length} written${lost.length ? `, lost: ${lost.slice(0, 3).join(', ')}` : ''}${twice.length ? `, twice: ${twice.slice(0, 3).join(', ')}` : ''})`);
const nums = (roadmap.items || []).map(x => x.number ?? x.id).filter(x => x !== undefined);
ok(new Set(nums).size === nums.length, `...and their numbers are unique (${nums.length})`);

// The bugs: every report exactly once, ids unique.
const bugs = await req('GET', '/api/bugs?project=alpha');
const titles = (bugs.bugs || []).map(b => b.title);
const wantB = sessions.flatMap(([who]) => [...Array(ROUNDS).keys()].map(i => `cc ${who} bug ${i}`));
const lostB = wantB.filter(t => !titles.includes(t)), twiceB = wantB.filter(t => titles.filter(x => x === t).length > 1);
const ids = (bugs.bugs || []).map(b => b.id);
ok(!lostB.length && !twiceB.length && new Set(ids).size === ids.length,
   `every bug landed exactly once with its own number (${wantB.length} filed${lostB.length ? `, lost: ${lostB.slice(0, 3).join(', ')}` : ''}${twiceB.length ? `, twice: ${twiceB.slice(0, 2).join(', ')}` : ''})`);

// The changelog: a file in the project, every entry once, the file whole.
const log = readFileSync(`${DIR}/ws/alpha/CHANGELOG.md`, 'utf8');
const wantC = sessions.flatMap(([who]) => [...Array(CHANGES).keys()].map(i => `cc ${who} change ${i}`));
// Whole lines: "change 1" is the start of "change 10", and a substring count
// read that as a duplicate. An entry is `- text`, and may end in a sha.
const lines = log.split('\n').map(l => l.replace(/\s*\([0-9a-f, ]+\)$/, ''));
const seen = t => lines.filter(l => l === `- ${t}`).length;
const lostC = wantC.filter(t => seen(t) === 0), twiceC = wantC.filter(t => seen(t) > 1);
ok(!lostC.length && !twiceC.length && /^# /.test(log),
   `every changelog entry landed exactly once and the file is whole (${wantC.length} logged${lostC.length ? `, lost ${lostC.length}: ${lostC.slice(0, 3).join(', ')}` : ''}${twiceC.length ? `, twice ${twiceC.length}` : ''})`);

// ---- the hooks every prompt fires, from every session at once ------------
// A session's hooks call the controller on each prompt and each edit: a note
// of the file it is about to change (which is how two people meet on one
// file), a question it asked, that it started, and what it has not been told
// about the notebook yet. Six sessions prompting together is these arriving
// together; every one must answer, the meeting on a shared file must be
// said, and nothing asked may go missing from the feed.
{
  const hook = (t, body) => req('POST', '/api/v1/hook', { project: 'alpha', ...body }, 'Bearer ' + t);
  const hjobs = [];
  for (const [who, t] of sessions) {
    hjobs.push(hook(t, { kind: 'started' }).then(r => ({ who, kind: 'started', r })));
    for (let i = 0; i < 8; i++) {
      hjobs.push(hook(t, { kind: 'note', path: 'shared/app.js' }).then(r => ({ who, kind: 'note', r })));
      hjobs.push(hook(t, { kind: 'note', path: `own/${who}-${i}.js` }).then(r => ({ who, kind: 'note', r })));
      hjobs.push(hook(t, { kind: 'seen' }).then(r => ({ who, kind: 'seen', r })));
    }
    for (let i = 0; i < 3; i++)
      hjobs.push(hook(t, { kind: 'asked', text: `cc ${who} asked ${i}` }).then(r => ({ who, kind: 'asked', r })));
  }
  const hs = await Promise.all(hjobs);
  const bad = hs.filter(x => x.r.status !== 200 || !x.r.ok);
  ok(bad.length === 0, `${hs.length} hooks from ${sessions.length} prompting sessions at once all answered${
    bad.length ? `: ${bad.slice(0, 3).map(x => `${x.who} ${x.kind} ${x.r.status} ${(x.r.error || '').slice(0, 40)}`).join(' | ')}` : ''}`);
  // The meeting: somebody else is on shared/app.js, by name, for somebody.
  const met = hs.filter(x => x.kind === 'note' && (x.r.others || []).length);
  ok(met.length > 0 && met.some(x => x.r.others.some(o => /cc\.|test/.test(o))),
     `two people on one file are told about each other (${met.length} notes named somebody else)`);
  const feed = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("chat", ${JSON.stringify(join(HERE, 'chat.py'))})
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
c.configure(state=${JSON.stringify(join(DIR, 'state'))}, write_json=lambda p, d: None)
print(json.dumps(c.feed("alpha")))`], { encoding: 'utf8' }).trim().split('\n').pop());
  const text = JSON.stringify(feed);
  const asked = sessions.flatMap(([who]) => [0, 1, 2].map(i => `cc ${who} asked ${i}`));
  const missing = asked.filter(a => !text.includes(a));
  ok(missing.length === 0, `every question a session asked is in the project's feed (${asked.length}${missing.length ? `, missing: ${missing.slice(0, 3).join(', ')}` : ''})`);
}

await done();
