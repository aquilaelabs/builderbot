// A person's editor on a project's files (R159): the controller's Files API
// and the VS Code extension in vscode/, which signs in as the person and can
// do nothing their account cannot. Every check here is the SERVER's answer
// for an account: with read and write, read only, no access, not on the
// project, a role that caps it at read, the editor's switch off, a session's
// token, taken off the project or signed out partway. Then the extension's
// own code, driven under a stand-in for VS Code's API against this server,
// and its terminal through the dashboard's /term relay to a real ttyd.
// No browser.
import { ok, done, DIR, URL } from './lib.mjs';
import { execFileSync, spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, symlinkSync, existsSync, statSync, utimesSync } from 'node:fs';
import { createRequire } from 'node:module';
import Module from 'node:module';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const require = createRequire(import.meta.url);
const { Client, Refused, signIn, API } = require(`${REPO}/vscode/lib/client.js`);
const { Ttyd } = require(`${REPO}/vscode/lib/ttyd.js`);
const base = URL.replace(/\/$/, '');
const ADMIN = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const admin = async (path, body) => {
  const r = await fetch(base + path, { method: 'POST', headers: ADMIN, body: JSON.stringify(body) });
  return { status: r.status, ...(await r.json().catch(() => ({}))) };
};
const env = { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` };
const addUser = (name, pw) => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', name, '--role', 'user'],
  { input: `${pw}\n${pw}\n`, encoding: 'utf8', env });
const uidOf = n => JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users[n].uid;
const tree = `${DIR}/ws/alpha`;
// The answer to one call: its status and words, never a throw.
const as = async (c, project, action, extra = {}) => {
  try { return { status: 200, ...(await c.files(project, action, extra)) }; }
  catch (e) { return { status: e.status || 0, error: e.message }; }
};

// ---- accounts, and what alpha's settings give each ----------------------------
const people = { 'ed.rw': 'edrwpass1', 'ed.r': 'edrpass12', 'ed.none': 'ednonepass1', 'ed.out': 'edoutpass1', 'ed.cap': 'edcappass1',
                 'ed.mem': 'edmempass1' };
for (const [n, pw] of Object.entries(people)) addUser(n, pw);
for (const n of ['ed.rw', 'ed.r', 'ed.none', 'ed.cap', 'ed.mem'])
  await admin('/api/users', { action: 'projects', name: n, projects: ['alpha'] });
// Each holds a role on alpha that gives the files area write, but ed.cap's
// gives read: its rw in the settings is capped at r by the role (R152 (f)).
await admin('/api/roles', { action: 'set', name: 'ed-files-w', scope: 'projects',
  perms: { projects: 'write', files: 'write' } });
await admin('/api/roles', { action: 'set', name: 'ed-files-r', scope: 'projects',
  perms: { projects: 'write', files: 'read' } });
// ed.none is on alpha with a role that gives no File access; ed.mem is on it
// with File access and no choice of its own on alpha's list, which since
// R104 is enough: being on the project is what lets a person's editor in.
await admin('/api/roles', { action: 'set', name: 'ed-nofiles', scope: 'projects', perms: { projects: 'write' } });
for (const n of ['ed.rw', 'ed.r', 'ed.mem'])
  await admin('/api/roles', { action: 'assign', name: n, project_roles: { alpha: ['ed-files-w'] } });
await admin('/api/roles', { action: 'assign', name: 'ed.none', project_roles: { alpha: ['ed-nofiles'] } });
await admin('/api/roles', { action: 'assign', name: 'ed.cap', project_roles: { alpha: ['ed-files-r'] } });
const set = await admin('/api/project-ftp', { action: 'set', project: 'alpha', editor: true,
  access: { [uidOf('ed.rw')]: 'rw', [uidOf('ed.r')]: 'r', [uidOf('ed.cap')]: 'rw' } });
ok(!set.error && set.editor === true && set.on === false,
   `alpha's File access opens it in an editor with FTPS left off: a door of its own (${JSON.stringify({ editor: set.editor, on: set.on })})`);

writeFileSync(`${tree}/editor-probe.txt`, 'first line\nneedle in a haystack\n');
mkdirSync(`${tree}/.git`, { recursive: true });
writeFileSync(`${tree}/.git/config`, '[remote "origin"]\n  url = https://x:ghp_secret@example.com/r.git\n');
try { symlinkSync('../beta', `${tree}/editor-escape`); } catch {}

const cookie = {};
for (const [n, pw] of Object.entries(people)) cookie[n] = await signIn(base, n, pw);
const c = Object.fromEntries(Object.keys(people).map(n => [n, new Client(base, cookie[n])]));
{
  let wrong = null;
  try { await signIn(base, 'ed.rw', 'not-the-password'); } catch (e) { wrong = e; }
  ok(Object.values(cookie).every(Boolean) && wrong instanceof Refused && /Wrong username or password/.test(wrong.message),
     'the extension signs in as the person, with the cookie the dashboard would give, and a wrong password is refused');
}

// ---- which projects each may open ------------------------------------------------
{
  const mine = {};
  for (const n of Object.keys(people)) mine[n] = (await c[n].projects()).projects;
  const acc = n => (mine[n].find(p => p.name === 'alpha') || {}).access || '';
  ok(acc('ed.rw') === 'rw' && acc('ed.r') === 'r' && acc('ed.cap') === 'r' && acc('ed.none') === '' && acc('ed.out') === ''
     && acc('ed.mem') === 'rw'
     && (await c['ed.rw'].projects()).api === API,
     `each is offered alpha exactly as far as the settings and roles give: rw, r, r capped by a role, none, not on it, and on it with no choice made (${
       Object.keys(people).map(n => `${n}=${acc(n) || '-'}`).join(' ')})`);
}

// ---- reading and writing, as each ----------------------------------------------------
{
  const read = {};
  for (const n of Object.keys(people)) read[n] = await as(c[n], 'alpha', 'read', { path: 'editor-probe.txt' });
  ok(read['ed.rw'].data && read['ed.r'].data && read['ed.cap'].data
     && read['ed.none'].status === 403 && /no file access/.test(read['ed.none'].error)
     && read['ed.out'].status === 400 && /not a project/.test(read['ed.out'].error),
     `a read is the server's to allow: rw, r and the capped read; no access is refused with why, and a project not theirs is not one (${
       read['ed.none'].error} | ${read['ed.out'].error})`);
  const data = Buffer.from('written from an editor\n').toString('base64');
  const w = {};
  for (const n of ['ed.rw', 'ed.r', 'ed.cap'])
    w[n] = await as(c[n], 'alpha', 'write', { path: 'editor-probe.txt', data, overwrite: true });
  ok(w['ed.rw'].ok && readFileSync(`${tree}/editor-probe.txt`, 'utf8') === 'written from an editor\n'
     && w['ed.r'].status === 403 && /read-only/.test(w['ed.r'].error) && w['ed.cap'].status === 403,
     `a write needs read and write: it lands for ed.rw, and read-only and the role-capped account are refused (${w['ed.r'].error})`);
  const st = await as(c['ed.r'], 'alpha', 'stat', { path: 'editor-probe.txt' });
  ok(st.readonly === true && (await as(c['ed.rw'], 'alpha', 'stat', { path: '' })).readonly === false,
     '...and stat tells the editor which, so a read-only project opens read-only');
  const rows = execFileSync('python3', ['-c', `
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
print("\\n".join(f"{p} {a} {t}" for p, a, t in db.execute("SELECT principal, action, target FROM audit WHERE action LIKE 'files-%'")))`,
    `${DIR}/state/builderbot.db`], { encoding: 'utf8' });
  ok(/user:ed\.rw files-write alpha:editor-probe\.txt/.test(rows) && !/ed\.r files-write/.test(rows),
     `every change is on the audit trail under the person's name, and a refused one is not (${rows.trim().split('\n')[0]})`);
}

// ---- what is never served -----------------------------------------------------------
{
  const rw = c['ed.rw'];
  const up = await as(rw, 'alpha', 'read', { path: '../beta/README.md' });
  const git = await as(rw, 'alpha', 'read', { path: '.git/config' });
  const link = await as(rw, 'alpha', 'list', { path: 'editor-escape' });
  const listed = await as(rw, 'alpha', 'list', { path: '' });
  ok(up.status === 400 && git.status === 403 && link.status === 403 && !listed.entries.some(([n]) => n === '.git'),
     `a path out of the project, through .git or through a symlink leading out is refused, and .git is never listed (${
       up.status} ${git.status} ${link.status})`);
  const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'], { encoding: 'utf8', env }).trim();
  const r = await fetch(base + '/api/v1/files', { method: 'POST', body: JSON.stringify({ action: 'list', project: 'alpha', path: '' }),
    headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' } });
  ok(r.status === 403, `a session's token is refused: a session has the tree, and is never a person (${r.status})`);
}

// ---- a save over a newer file, search, and changes as they happen --------------------
{
  const rw = c['ed.rw'];
  const first = await as(rw, 'alpha', 'read', { path: 'editor-probe.txt' });
  writeFileSync(`${tree}/editor-probe.txt`, 'Claude saved this meanwhile\nneedle\n');
  utimesSync(`${tree}/editor-probe.txt`, new Date(), new Date(Date.now() + 5000));
  const late = await as(rw, 'alpha', 'write', { path: 'editor-probe.txt', overwrite: true, mtime: first.mtime,
    data: Buffer.from('mine').toString('base64') });
  ok(late.status === 409 && /changed on the controller/.test(late.error)
     && readFileSync(`${tree}/editor-probe.txt`, 'utf8').startsWith('Claude saved'),
     `a save over a file changed since it was read is refused, and what was saved meanwhile stays (${late.error})`);
  const found = await as(c['ed.r'], 'alpha', 'search', { query: 'needle' });
  const none = await as(c['ed.none'], 'alpha', 'search', { query: 'needle' });
  ok(found.matches?.some(m => m.path === 'editor-probe.txt' && m.line === 2) && none.status === 403
     && !found.matches.some(m => m.path.startsWith('.git')),
     `search finds a line across the tree for an account that may read it, never in .git, and not for one that may not (${found.matches?.length} matches)`);
  const start = await as(c['ed.r'], 'alpha', 'changes', { since: 0 });
  const waiting = as(c['ed.r'], 'alpha', 'changes', { since: start.rev, wait: 15 });
  await new Promise(r => setTimeout(r, 500));
  writeFileSync(`${tree}/claude-wrote-this.txt`, 'new\n');
  const t0 = Date.now();
  const got = await waiting;
  ok(got.changes?.some(x => x.path === 'claude-wrote-this.txt' && x.type === 'created') && Date.now() - t0 < 8000,
     `a file a session writes is told to a waiting editor within seconds (${JSON.stringify(got.changes)} in ${Date.now() - t0} ms)`);
}

// ---- access taken away, partway --------------------------------------------------------
{
  await admin('/api/roles', { action: 'assign', name: 'ed.r', project_roles: { alpha: ['ed-nofiles'] } });
  const gone = await as(c['ed.r'], 'alpha', 'read', { path: 'editor-probe.txt' });
  await admin('/api/users', { action: 'projects', name: 'ed.cap', projects: [] });
  const off = await as(c['ed.cap'], 'alpha', 'list', { path: '' });
  await admin('/api/project-ftp', { action: 'set', project: 'alpha', editor: false });
  const shut = await as(c['ed.rw'], 'alpha', 'list', { path: '' });
  await admin('/api/project-ftp', { action: 'set', project: 'alpha', editor: true });
  ok(gone.status === 403 && off.status === 400 && shut.status === 403 && /off in its settings/.test(shut.error),
     `access taken away holds on the next request with the same sign-in: the role's File access, the project, the editor's switch (${gone.status} ${off.status} ${shut.status})`);
  execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'passwd', 'ed.rw'], { input: 'edrwpass2\nedrwpass2\n', encoding: 'utf8', env });
  const out = await as(c['ed.rw'], 'alpha', 'list', { path: '' });
  ok(out.status === 401 && /Sign In/.test(out.error), `...and a password change signs the extension out (${out.status}: ${out.error})`);
  cookie['ed.rw'] = await signIn(base, 'ed.rw', 'edrwpass2');
  c['ed.rw'] = new Client(base, cookie['ed.rw']);
}

// ---- the extension itself, under a stand-in for VS Code -------------------------------
// The parts of VS Code's API it uses, enough to drive its file system as
// VS Code would: activate, register, stat, read, write, watch.
{
  const fired = [];
  class Emitter { constructor() { this.subs = []; this.event = f => { this.subs.push(f); return { dispose() {} }; }; }
    fire(x) { fired.push(x); this.subs.forEach(f => f(x)); } }
  const settings = { url: base, allowSelfSignedCertificate: false };
  const secrets = new Map([[`builderbot.cookie:${base}`, cookie['ed.rw']]]);
  let provider = null;
  class FsErr extends Error {}
  const vscode = {
    EventEmitter: Emitter,
    Disposable: class { constructor(f) { this.dispose = f; } },
    FileType: { File: 1, Directory: 2 },
    FilePermission: { Readonly: 1 },
    FileChangeType: { Changed: 1, Created: 2, Deleted: 3 },
    FileSystemError: { FileNotFound: u => new FsErr(`notfound ${u}`), FileExists: u => new FsErr(`exists ${u}`),
                       NoPermissions: m => new FsErr(`noperm ${m}`), Unavailable: m => new FsErr(`unavailable ${m}`) },
    Uri: { from: o => ({ ...o, toString() { return `${o.scheme}://${o.authority}${o.path}`; } }) },
    ConfigurationTarget: { Global: 1 },
    workspace: {
      getConfiguration: () => ({ get: k => settings[k], update: async (k, v) => { settings[k] = v; } }),
      registerFileSystemProvider: (s, p) => { provider = p; return { dispose() {} }; },
      onDidChangeConfiguration: () => ({ dispose() {} }),
      workspaceFolders: [],
    },
    window: { showWarningMessage() {}, showErrorMessage: m => errors.push(m), showInformationMessage() {},
              showInputBox: async () => 'again', showQuickPick: async items => items.find(i => i.project === 'alpha') || items[0],
              showTextDocument: async u => { const ed = { uri: u, revealRange: r => { ed.revealed = r; } }; opened.push(ed); return ed; } },
    Position: class { constructor(l, c) { this.line = l; this.character = c; } translate(dl, dc) { return new vscode.Position(this.line + dl, this.character + dc); } },
    Selection: class { constructor(a, b) { this.anchor = a; this.active = b; } },
    Range: class { constructor(a, b) { this.start = a; this.end = b; } },
    commands: { registerCommand: (id, f) => { commands[id] = f; return { dispose() {} }; } },
  };
  const commands = {}, opened = [], errors = [];
  const load = Module._load;
  Module._load = function (req, ...rest) { return req === 'vscode' ? vscode : load.call(this, req, ...rest); };
  const ext = require(`${REPO}/vscode/extension.js`);
  Module._load = load;
  ext.activate({ subscriptions: [], secrets: { get: async k => secrets.get(k), store: async (k, v) => secrets.set(k, v),
                                                delete: async k => secrets.delete(k) } });
  const uri = path => vscode.Uri.from({ scheme: 'builderbot', path: '/alpha' + path });
  const dir = await provider.readDirectory(uri('/'));
  const text = Buffer.from(await provider.readFile(uri('/editor-probe.txt'))).toString();
  const s = await provider.stat(uri('/editor-probe.txt'));
  ok(dir.some(([n, t]) => n === 'editor-probe.txt' && t === 1) && !dir.some(([n]) => n === '.git')
     && /Claude saved/.test(text) && s.type === 1 && !s.permissions,
     `the extension's file system lists, reads and stats a project as VS Code asks it to (${dir.length} entries)`);
  await provider.writeFile(uri('/from-vscode.txt'), Buffer.from('saved in VS Code\n'), { create: true, overwrite: false });
  ok(readFileSync(`${tree}/from-vscode.txt`, 'utf8') === 'saved in VS Code\n', '...and a save lands in the project\'s tree');
  writeFileSync(`${tree}/editor-probe.txt`, 'Claude again\n');
  utimesSync(`${tree}/editor-probe.txt`, new Date(), new Date(Date.now() + 9000));
  let refused = null;
  try { await provider.writeFile(uri('/editor-probe.txt'), Buffer.from('stale'), { create: false, overwrite: true }); }
  catch (e) { refused = e; }
  ok(refused && /changed on the controller/.test(refused.message) && readFileSync(`${tree}/editor-probe.txt`, 'utf8') === 'Claude again\n',
     `...a save over a file Claude changed since it was opened is refused, keeping Claude's (${refused?.message})`);
  await commands['builderbot.search']();
  const ed = opened[0];
  ok(!errors.length && ed && /^\/alpha\//.test(ed.uri.path) && ed.selection?.active.character - ed.selection?.anchor.character === 'again'.length,
     `...Search Project Files opens the match it picked with the word selected (${errors[0] || ed?.uri.path})`);
  const w = provider.watch(uri('/'), { recursive: true, excludes: [] });
  await new Promise(r => setTimeout(r, 1500));
  writeFileSync(`${tree}/watched.txt`, 'appears\n');
  const t0 = Date.now();
  while (!fired.flat().some(e => e.uri?.path === '/alpha/watched.txt') && Date.now() - t0 < 12000)
    await new Promise(r => setTimeout(r, 200));
  w.dispose();
  ok(fired.flat().some(e => e.uri?.path === '/alpha/watched.txt' && e.type === 2),
     `...and a file a session writes is told to VS Code as created, for open editors to follow (${Date.now() - t0} ms)`);
}

// ---- the session's terminal, through the dashboard's relay ------------------------------
{
  const has = (() => { try { execFileSync('sh', ['-c', 'command -v ttyd'], { stdio: 'ignore' }); return true; } catch { return false; } })();
  if (!has) {
    console.log('SKIP  ttyd is not on this machine: the terminal bridge was not driven');
  } else {
    // Where the harness's server relays /term (DASHBOARD_TTYD_PORT and the
    // read-only twin one above): a ttyd that says what it was handed.
    const show = ['bash', '-c', 'echo "ARGS $*"; exec bash --norc', '_'];
    const tty = [spawn('ttyd', ['-p', '7999', '-i', '127.0.0.1', '-a', '-W', ...show], { stdio: 'ignore' }),
                 spawn('ttyd', ['-p', '8000', '-i', '127.0.0.1', '-a', ...show], { stdio: 'ignore' })];
    await new Promise(r => setTimeout(r, 800));
    try {
      const owner = new Client(base, await signIn(base, 'test', 'test'));
      const t = new Ttyd(owner, 'sh:1:alpha');
      let out = '';
      t.on('output', s => { out += s; });
      await t.open(90, 20);
      await new Promise(r => setTimeout(r, 600));
      t.write('echo $((6*7))\r');
      await new Promise(r => setTimeout(r, 800));
      t.close();
      const uid = uidOf('test');
      ok(new RegExp(`ARGS u:${uid}:sh:1:alpha`).test(out) && /\b42\b/.test(out),
         `the terminal is the dashboard's: the relay stamps whose it is before ttyd sees it, and what is typed runs (${
           out.replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, '').replace(/\s+/g, ' ').slice(0, 80)})`);
      let no = null;
      try { await new Ttyd(c['ed.out'], 'sh:1:alpha').open(80, 24); } catch (e) { no = e; }
      ok(no && no.status >= 400, `...and the same relay refuses a terminal the account may not open (${no?.status} ${String(no?.message).slice(0, 80)})`);
    } finally {
      tty.forEach(p => p.kill());
    }
  }
}

await done();
