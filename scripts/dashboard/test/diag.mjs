// The controller's diagnostics (diag.py, POST /api/diag, bb diag). No
// browser: it is the gate and the report, asked for with real credentials.
// An administrator reads it anywhere. A session reads it only when debug mode
// is on, its node is ticked for it on Debug settings, and its account is an
// administrator's, because a node is shared and the tick alone would hand it
// to every tester whose session runs there. Whatever it returns carries no
// credential. Nothing it makes is left behind, and what it touches is put back:
// the account, the node's tick, the project's node and the switch.
import { ok, done, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

const base = URL.replace(/\/$/, '');
const HERE = new globalThis.URL('..', import.meta.url).pathname;
const basic = (u, p) => ({ Authorization: 'Basic ' + Buffer.from(`${u}:${p}`).toString('base64'),
                           'Content-Type': 'application/json' });
const ADMIN = basic('test', 'test');
const call = async (path, body, headers = ADMIN) => {
  const r = await fetch(base + path, body === undefined ? { headers }
    : { method: 'POST', headers, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json().catch(() => ({})) };
};
const usersPy = code => execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", ${JSON.stringify(join(HERE, 'users.py'))})
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state=${JSON.stringify(join(DIR, 'state'))}, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
${code}`], { encoding: 'utf8' }).trim();
const ownerUid = usersPy('print(next(r["uid"] for r in u.load()["users"].values() if r.get("role") == "owner"))');
const tok = uid => usersPy(`print(u.mint_session("alpha", uid=${JSON.stringify(uid)}))`);
const bearer = t => ({ Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' });
const CRED = /bb[a-z]_[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}|password\s*[:=]\s*\S{6,}/;

// ---- an administrator ------------------------------------------------------
{
  const r = await call('/api/diag', {});
  const secs = Object.keys(r.body).filter(k => k !== 'at');
  ok(r.status === 200 && ['controller', 'images', 'settings', 'doctor', 'nodes', 'jobs', 'errors', 'audit']
       .every(s => secs.includes(s)),
     `an administrator reads the whole report (${r.status}: ${secs.join(',')})`);
  ok(typeof r.body.controller?.agent_shipped === 'string' && 'debug_mode' in (r.body.settings || {})
     && Array.isArray(r.body.doctor?.checks) && typeof r.body.jobs?.last_24h === 'object',
     '...with the build it ships, the switches, the doctor and the jobs in it');
  const one = await call('/api/diag', { sections: ['nodes', 'nosuch'] });
  ok(one.status === 200 && Array.isArray(one.body.nodes) && !('audit' in one.body),
     '...or only the sections asked for, an unknown one ignored');
  ok(!CRED.test(JSON.stringify(r.body)), 'and nothing in it is shaped like a credential');
}

// bb diag, the way a person reads it: the verb against this server.
{
  const out = (() => { try {
    return execFileSync('bash', [join(HERE, '..', 'bb'), 'diag', 'controller', 'nodes', 'jobs'],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', BB_CONTROLLER: base,
               DASHBOARD_AUTH: 'test:test' } });
  } catch (e) { return `EXIT ${e.status}: ${e.stdout || ''}${e.stderr || ''}`; } })();
  ok(/== controller ==/.test(out) && /ships agent/.test(out) && /== jobs ==/.test(out)
     && /last 24h:/.test(out) && !/== audit ==/.test(out),
     `bb diag prints the sections asked for, readably (${out.trim().split('\n').slice(0, 3).join(' | ').slice(0, 90)})`);
}

// The redactor on its own, over the shapes it exists for.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util
spec = importlib.util.spec_from_file_location("diag", ${JSON.stringify(join(HERE, 'diag.py'))})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.redact("GET /x?t=bbs_abcdefgh1234 Authorization: Bearer abc.def.ghi password=hunter22 ghp_0123456789abcdefABCD kept words"))
`], { encoding: 'utf8' }).trim();
  ok(!CRED.test(out) && !/hunter22|abc\.def\.ghi/.test(out) && /kept words/.test(out),
     `the redactor takes tokens, headers and passwords out and leaves the words (${out})`);
}

// ---- a session: the switch, the node's tick, the account --------------------
// On the agent node the harness already has, never a new one: a node cannot
// be deleted, only revoked, and a row left behind is in every later file's
// node list. What is touched is read first and put back exactly: that node's
// tick, alpha's node and the switch.
{
  const prefsPy = code => execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("prefs", ${JSON.stringify(join(HERE, 'prefs.py'))})
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
p.configure(state=${JSON.stringify(join(DIR, 'state'))}, write_json=lambda f, d: open(f, "w").write(json.dumps(d)))
${code}`], { encoding: 'utf8' }).trim();
  const node = ((await call('/api/v1/nodes')).body.nodes || []).find(x => x.kind === 'agent' && x.state !== 'retired');
  ok(!!node, `the harness has an agent node to ask from (${node?.name})`);
  const wasNode = prefsPy('print(p.get("alpha").get("node") or "")');
  const wasDiag = !!node.config?.diag, wasFrom = node.config?.log_from || [];
  const wasDebug = !!(await call('/api/diag', { sections: ['settings'] })).body.settings?.debug_mode;
  await call('/api/prefs', { project: 'alpha', node: node.id });
  const plainUid = usersPy(`
d = u.load()
uid = u.mint_uid()
d["users"]["diag.plain"] = {"uid": uid, "role": "user", "projects": ["alpha"],
                            "prefs": {"full_name": "Diag Plain", "email": "dp@example.invalid"},
                            "password": u.hash_password("diag-plain-pw"), "created": 0, "seen": 0}
u._save(d)
print(uid)`);
  const asAdmin = bearer(tok(ownerUid)), asPlain = bearer(tok(plainUid));
  await call('/api/settings', { set: { debug_mode: false } });
  await call('/api/v1/nodes', { action: 'log-grant', id: node.id, from: wasFrom, diag: false });

  let r = await call('/api/diag', {}, asAdmin);
  ok(r.status === 403 && /debug mode is off/.test(r.body.error || ''),
     `with debug mode off, an administrator's session is refused, saying why (${r.body.error})`);
  await call('/api/settings', { set: { debug_mode: true } });
  r = await call('/api/diag', {}, asAdmin);
  ok(r.status === 403 && new RegExp(`${node.name} has not been granted`).test(r.body.error || ''),
     `...and on, still refused until its node is ticked (${r.body.error})`);
  const g = (await call('/api/v1/nodes', { action: 'log-grant', id: node.id, from: wasFrom, diag: true })).body;
  ok(g.ok && g.diag === true, 'the tick is set with the log grant, on the node\'s record');
  r = await call('/api/diag', {}, asAdmin);
  ok(r.status === 200 && Array.isArray(r.body.nodes) && r.body.nodes.some(n => n.name === node.name),
     `...then an administrator's session on that node reads the report (${r.status})`);
  r = await call('/api/diag', {}, asPlain);
  ok(r.status === 403 && /administrator's/.test(r.body.error || ''),
     `a plain account's session on the same ticked node is refused: the tick is not a tester's (${r.body.error})`);
  r = await call('/api/diag', {}, basic('diag.plain', 'diag-plain-pw'));
  ok(r.status === 403, `...and so is that account with its password (${r.status})`);
  const log = (await call('/api/v1/nodes', { action: 'log-grant', id: node.id, from: wasFrom })).body;
  ok(log.ok && log.diag === true, 'a log grant saved without the tick leaves the tick as it was');

  // Everything back as it was found.
  await call('/api/v1/nodes', { action: 'log-grant', id: node.id, from: wasFrom, diag: wasDiag });
  await call('/api/settings', { set: { debug_mode: wasDebug } });
  await call('/api/prefs', { project: 'alpha', node: wasNode });
  usersPy('d = u.load(); d["users"].pop("diag.plain", None); u._save(d)');
  const after = ((await call('/api/v1/nodes')).body.nodes || []).find(x => x.id === node.id);
  ok(prefsPy('print(p.get("alpha").get("node") or "")') === wasNode && !!after?.config?.diag === wasDiag,
     `...and what it touched is as it was: alpha's node (${wasNode || 'none'}) and the node's tick`);
}

await done();
