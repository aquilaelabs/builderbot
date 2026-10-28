'use strict';
// BuilderBot for VS Code (R159): a project's files opened as a folder of
// their own, builderbot:/PROJECT/..., read and saved through the
// controller's Files API, with no share mounted here; the changes a coding
// agent's session makes appear in open editors as it saves them; and any
// agent's session terminal in a VS Code panel. Signed in as the person: the server decides
// on every request what their account may do, and this only shows its
// answer. Plain JavaScript and Node's own modules, so there is nothing to
// build or install beside it.
const vscode = require('vscode');
const { Client, Refused, signIn } = require('./lib/client');
const { Term } = require('./lib/term');

const SCHEME = 'builderbot';
const SECRET = 'builderbot.cookie';

let client = null;
let fsp = null;

function base() {
  return (vscode.workspace.getConfiguration('builderbot').get('url') || '').replace(/\/+$/, '');
}

function tls() {
  return { rejectUnauthorized: !vscode.workspace.getConfiguration('builderbot').get('allowSelfSignedCertificate') };
}

async function connect(context) {
  if (client) return client;
  const url = base();
  const cookie = url ? await context.secrets.get(`${SECRET}:${url}`) : '';
  if (!url || !cookie) throw new Refused(401, 'Not signed in to BuilderBot: run BuilderBot: Sign In.');
  client = new Client(url, cookie, tls());
  return client;
}

// A server's refusal as VS Code's own kind of error, with the server's words.
function asFsError(e, uri) {
  if (!(e instanceof Refused)) return e;
  if (e.status === 404) return vscode.FileSystemError.FileNotFound(uri);
  if (e.status === 409 && /exists/.test(e.message)) return vscode.FileSystemError.FileExists(uri);
  if (e.status === 401 || e.status === 403) return vscode.FileSystemError.NoPermissions(e.message);
  return vscode.FileSystemError.Unavailable(e.message);
}

const TYPE = { file: vscode.FileType.File, dir: vscode.FileType.Directory };

class BuilderBotFS {
  constructor(context) {
    this.context = context;
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeFile = this.emitter.event;
    this.seen = new Map();           // uri -> mtime read, so a save over a newer one is refused
    this.watchers = new Map();       // project -> {count, stop}
  }

  // builderbot:/PROJECT/PATH: the project is the path's first part, so VS
  // Code names the folder after it (in the host part it was named "/").
  where(uri) {
    const [project, ...rest] = uri.path.replace(/^\/+/, '').split('/');
    return { project, path: rest.join('/') };
  }

  async call(uri, action, extra = {}) {
    const { project, path } = this.where(uri);
    try {
      return await (await connect(this.context)).files(project, action, { path, ...extra });
    } catch (e) {
      throw asFsError(e, uri);
    }
  }

  async stat(uri) {
    const s = await this.call(uri, 'stat');
    return { type: TYPE[s.type], size: s.size, mtime: s.mtime, ctime: s.ctime,
             ...(s.readonly ? { permissions: vscode.FilePermission.Readonly } : {}) };
  }

  async readDirectory(uri) {
    const j = await this.call(uri, 'list');
    return j.entries.map(([name, kind]) => [name, TYPE[kind]]);
  }

  async readFile(uri) {
    const j = await this.call(uri, 'read');
    this.seen.set(uri.toString(), j.mtime);
    return Buffer.from(j.data, 'base64');
  }

  async writeFile(uri, content, options) {
    const j = await this.call(uri, 'write', {
      data: Buffer.from(content).toString('base64'), create: !!options.create, overwrite: !!options.overwrite,
      // Saved over what was read: changed since (Claude's save), it is
      // refused and VS Code offers its compare.
      ...(this.seen.has(uri.toString()) ? { mtime: this.seen.get(uri.toString()) } : {}),
    });
    this.seen.set(uri.toString(), j.mtime);
  }

  async createDirectory(uri) {
    await this.call(uri, 'mkdir');
  }

  async delete(uri, options) {
    await this.call(uri, 'delete', { recursive: !!options.recursive });
  }

  async rename(oldUri, newUri, options) {
    await this.call(oldUri, 'rename', { to: this.where(newUri).path, overwrite: !!options.overwrite });
  }

  // Whatever VS Code watches in a project, one long poll per project for
  // what changed on the controller, fired as VS Code's own change events.
  watch(uri) {
    const { project } = this.where(uri);
    let w = this.watchers.get(project);
    if (!w) {
      w = { count: 0, stopped: false };
      this.watchers.set(project, w);
      this.follow(project, w);
    }
    w.count += 1;
    return new vscode.Disposable(() => {
      w.count -= 1;
      if (w.count <= 0) { w.stopped = true; this.watchers.delete(project); }
    });
  }

  async follow(project, w) {
    let since = 0, wait = 0;
    while (!w.stopped) {
      try {
        const c = await connect(this.context);
        const j = await c.files(project, 'changes', { since, wait });
        if (since && j.changes && j.changes.length) {
          this.emitter.fire(j.changes.map(x => ({
            uri: at(project, x.path),
            type: x.type === 'created' ? vscode.FileChangeType.Created
              : x.type === 'deleted' ? vscode.FileChangeType.Deleted : vscode.FileChangeType.Changed,
          })));
        }
        since = j.rev;
        wait = 20;
        if (j.reset) await sleep(10000);
      } catch (e) {
        // Access taken away or signed out: the server said so; stop asking.
        if (e instanceof Refused && (e.status === 401 || e.status === 403)) {
          vscode.window.showWarningMessage(`BuilderBot stopped following ${project}: ${e.message}`);
          return;
        }
        await sleep(5000);
      }
    }
  }
}

function at(project, path = '') {
  return vscode.Uri.from({ scheme: SCHEME, path: `/${project}${path ? '/' + path : ''}` });
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function say(e) {
  vscode.window.showErrorMessage(`BuilderBot: ${e.message || e}`);
}

async function pickProject(context, why) {
  const c = await connect(context);
  // Too new for its controller, said plainly; too old, the controller
  // refused the call above with its own words (426), which say() shows.
  const { projects, tooOld } = await c.projects();
  if (tooOld) vscode.window.showWarningMessage(tooOld);
  if (!projects.length) {
    throw new Error('no project here is open to you in an editor. Its settings (File access) say who may, '
      + 'and whether opening it in an editor is on.');
  }
  // An archived project is out of sight (R119): last, and said so. A lock
  // that holds this account out says why, and leaves it read only.
  const shown = [...projects.filter(p => !p.archived), ...projects.filter(p => p.archived)];
  const pick = await vscode.window.showQuickPick(shown.map(p => ({
    label: p.name,
    description: [p.access === 'rw' ? 'read and write' : 'read only', p.locked ? 'locked' : '', p.archived ? 'archived' : '']
      .filter(Boolean).join(', '),
    ...(p.locked_why ? { detail: p.locked_why } : {}),
    project: p.name,
  })), { placeHolder: why });
  return pick && pick.project;
}

// The coding agents a session may run (R95), the live rows of the
// dashboard's table (scripts/dashboard/agents.py, held to it by
// unit/test_agents.py): a session's terminal is `ID:PROJECT`, whichever it is.
const AGENTS = [
  { id: 'claude', name: 'Claude', product: 'Claude Code' },
  { id: 'codex', name: 'ChatGPT', product: 'Codex CLI' },
  { id: 'copilot', name: 'Copilot', product: 'Copilot CLI' },
  { id: 'grok', name: 'Grok', product: 'Grok Build' },
  { id: 'open', name: 'Any model', product: 'OpenCode' },
];

// The terminal argument that opens an agent's session on a project, as the
// dashboard's Start and Open build it, with the boot of the machine it is
// for last (page-tabs.js bootFor): bb-tty attaches to a running session
// whatever the boot, and starts one only for the boot it is running now.
function sessionArg(agent, project, boot = '') {
  return `${(AGENTS.find(a => a.id === agent) || AGENTS[0]).id}:${project}${boot ? `:b:${boot}` : ''}`;
}

// What the status says of one project for this account: the boot a new
// session there needs, and which agents' sessions of its own run. A
// status that does not answer leaves both empty: an open then attaches to
// a running session and says so in the terminal when there is none.
async function sessionFacts(c, project) {
  let st = {};
  try { st = await c.status(); } catch { st = {}; }
  const row = (st.projects || []).find(p => p.name === project) || {};
  const names = new Set((st.sessions || []).map(s => s.name));
  const tmux = s => s.replace(/[.:]/g, '_');
  const running = new Set(AGENTS.filter(a => names.has((st.tmux_prefix || '') + tmux(`${a.id}-${project}`))).map(a => a.id));
  return { boot: row.session_boot || st.boot || '', running };
}

async function pickAgent(project, running) {
  const pick = await vscode.window.showQuickPick(AGENTS.map(a => ({
    label: a.name, description: running.has(a.id) ? `${a.product}, running` : a.product, agent: a.id,
  })), { placeHolder: `Which agent's session on ${project}: opened if it runs, started if not` });
  return pick && pick.agent;
}

// Signed in with a name and password, through the same /login as a browser:
// the command's work, and what the extension exports for a script or a test
// to sign in without the input boxes.
async function signInWith(context, url, name, password) {
  const clean = url.replace(/\/+$/, '');
  const cookie = await signIn(clean, name, password, tls());
  await vscode.workspace.getConfiguration('builderbot').update('url', clean, vscode.ConfigurationTarget.Global);
  await context.secrets.store(`${SECRET}:${clean}`, cookie);
  client = null;
}

async function cmdSignIn(context) {
  const url = await vscode.window.showInputBox({
    prompt: 'BuilderBot\'s address, as you open the dashboard', value: base() || 'https://', ignoreFocusOut: true,
  });
  if (!url) return;
  const name = await vscode.window.showInputBox({ prompt: 'Your BuilderBot name', ignoreFocusOut: true });
  if (!name) return;
  const password = await vscode.window.showInputBox({ prompt: `${name}'s BuilderBot password`, password: true, ignoreFocusOut: true });
  if (!password) return;
  try {
    await signInWith(context, url, name, password);
    vscode.window.showInformationMessage(`Signed in to BuilderBot as ${name}.`);
  } catch (e) {
    say(e);
  }
}

async function cmdSignOut(context) {
  const url = base();
  if (url) await context.secrets.delete(`${SECRET}:${url}`);
  client = null;
  vscode.window.showInformationMessage('Signed out of BuilderBot here.');
}

async function cmdOpenProject(context) {
  try {
    const project = await pickProject(context, 'A project to open as a folder');
    if (!project) return;
    const n = (vscode.workspace.workspaceFolders || []).length;
    vscode.workspace.updateWorkspaceFolders(n, 0, { uri: at(project), name: `${project} (BuilderBot)` });
  } catch (e) {
    say(e);
  }
}

// Any coding agent's session on a project (R128): the project, then which
// agent, unless the caller named them (`builderbot.openSession` with a
// project, and an agent's id after it).
async function cmdOpenSession(context, project, agent) {
  try {
    project = typeof project === 'string' ? project : await pickProject(context, 'Which project\'s agent session to open');
    if (!project) return;
    const c = await connect(context);
    const facts = await sessionFacts(c, project);
    agent = typeof agent === 'string' ? agent : await pickAgent(project, facts.running);
    if (!agent) return;
    const a = AGENTS.find(x => x.id === agent) || AGENTS[0];
    const t = new Term(c, sessionArg(a.id, project, facts.boot));
    const write = new vscode.EventEmitter();
    const closed = new vscode.EventEmitter();
    const pty = {
      onDidWrite: write.event,
      onDidClose: closed.event,
      open: async dims => {
        t.on('output', s => write.fire(s));
        // Why it ended stays on screen, as in the dashboard's tab; one
        // that ended with nothing to say closes.
        t.on('close', why => { if (why) write.fire(`\r\n[BuilderBot] ${why}\r\n`); else closed.fire(); });
        t.on('error', e => write.fire(`\r\n[BuilderBot] ${e.message}\r\n`));
        try {
          await t.open(dims ? dims.columns : 80, dims ? dims.rows : 24);
        } catch (e) {
          write.fire(`\r\n[BuilderBot] ${e.message}\r\n`);
          closed.fire();
        }
      },
      close: () => t.close(),
      handleInput: data => t.write(data),
      setDimensions: dims => t.resize(dims.columns, dims.rows),
    };
    const term = vscode.window.createTerminal({ name: `${a.name}: ${project}`, pty });
    term.show();
  } catch (e) {
    say(e);
  }
}

async function cmdSearch(context) {
  try {
    const folder = (vscode.workspace.workspaceFolders || []).find(f => f.uri.scheme === SCHEME);
    const project = folder ? fsp.where(folder.uri).project : await pickProject(context, 'A project to search');
    if (!project) return;
    const query = await vscode.window.showInputBox({ prompt: `Search ${project}'s files for` });
    if (!query) return;
    const j = await (await connect(context)).files(project, 'search', { query });
    const pick = await vscode.window.showQuickPick(j.matches.map(m => ({
      label: `${m.path}:${m.line}`, description: m.text.trim().slice(0, 120), m,
    })), { placeHolder: `${j.matches.length}${j.complete ? '' : '+'} matches`, matchOnDescription: true });
    if (!pick) return;
    // Named pos, not at: a const at here would shadow the function above
    // and the call before it would throw (it did, on every pick).
    const editor = await vscode.window.showTextDocument(at(project, pick.m.path));
    const pos = new vscode.Position(pick.m.line - 1, pick.m.col);
    editor.selection = new vscode.Selection(pos, pos.translate(0, pick.m.len));
    editor.revealRange(new vscode.Range(pos, pos));
  } catch (e) {
    say(e);
  }
}

function activate(context) {
  fsp = new BuilderBotFS(context);
  context.subscriptions.push(
    vscode.workspace.registerFileSystemProvider(SCHEME, fsp, { isCaseSensitive: true }),
    vscode.commands.registerCommand('builderbot.signIn', () => cmdSignIn(context)),
    vscode.commands.registerCommand('builderbot.signOut', () => cmdSignOut(context)),
    vscode.commands.registerCommand('builderbot.openProject', () => cmdOpenProject(context)),
    vscode.commands.registerCommand('builderbot.openSession', (p, a) => cmdOpenSession(context, p, a)),
    vscode.commands.registerCommand('builderbot.search', () => cmdSearch(context)),
    vscode.workspace.onDidChangeConfiguration(e => { if (e.affectsConfiguration('builderbot')) client = null; }),
  );
  return { signIn: (url, name, password) => signInWith(context, url, name, password) };
}

function deactivate() {
  if (fsp) for (const w of fsp.watchers.values()) w.stopped = true;
}

module.exports = { activate, deactivate, BuilderBotFS, AGENTS, sessionArg, sessionFacts };
