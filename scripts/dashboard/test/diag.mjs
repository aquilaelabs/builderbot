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

// ---- a session: the switch, the project's grant, the account's grant -------
// Per project since 6 Oct: the grant is alpha's (its settings' Debug), not
// the node's, and the account must hold `debug`, which only the owner has
// until a role names it; the built-in admin's "everything" leaves it out.
// What is touched is read first and put back: alpha's node and grants and
// the switch.
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
  const wasDiag = prefsPy('print(p.get("alpha").get("diag"))') === 'True';
  const wasDebug = !!(await call('/api/diag', { sections: ['settings'] })).body.settings?.debug_mode;
  await call('/api/prefs', { project: 'alpha', node: node.id });
  const mk = (name, role) => usersPy(`
d = u.load()
uid = u.mint_uid()
d["users"]["${name}"] = {"uid": uid, "role": "${role}", "projects": ["alpha"],
                        "prefs": {"full_name": "${name}", "email": "${name}@example.invalid"},
                        "password": u.hash_password("${name}-pw"), "created": 0, "seen": 0}
u._save(d)
print(uid)`);
  const plainUid = mk('diag.plain', 'user'), adminUid = mk('diag.admin', 'admin');
  const asOwner = bearer(tok(ownerUid)), asPlain = bearer(tok(plainUid)), asAdmin = bearer(tok(adminUid));
  await call('/api/settings', { set: { debug_mode: false } });
  await call('/api/prefs', { project: 'alpha', diag: false, log_from: [] });

  let r = await call('/api/diag', {}, asOwner);
  ok(r.status === 403 && /debug mode is off/.test(r.body.error || ''),
     `with debug mode off, the owner's session is refused, saying why (${r.body.error})`);
  await call('/api/settings', { set: { debug_mode: true } });
  r = await call('/api/diag', {}, asOwner);
  ok(r.status === 403 && /alpha has not been granted the controller's diagnostics: Debug in its settings/.test(r.body.error || ''),
     `...and on, still refused until the PROJECT is granted it (${r.body.error})`);
  const g = (await call('/api/prefs', { project: 'alpha', diag: true })).body;
  ok(!g.error && prefsPy('print(p.get("alpha").get("diag"))') === 'True', `the grant is the project's (${g.error || 'set'})`);
  r = await call('/api/diag', {}, asOwner);
  ok(r.status === 200 && Array.isArray(r.body.nodes) && r.body.nodes.some(n => n.name === node.name),
     `...then the owner's session on alpha reads the report (${r.status})`);
  // The node's own jobs the report lists open for the same reader (B547):
  // a system job by its id and in the listing, through the redactor, and
  // for nobody without the grant. Queued straight into the harness's store.
  const sysJob = execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location('nodes', ${JSON.stringify(join(HERE, 'nodes.py'))})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(state=${JSON.stringify(join(DIR, 'state'))})
print(json.dumps(m.job_add('system', {'node': '${node.id}'}, 'exec', {'argv': ['echo', 'password=hunter22']})))`],
    { encoding: 'utf8' }).trim().split('\n').pop();
  const jid = JSON.parse(sysJob).job;
  r = await call(`/api/v1/jobs?id=${jid}`, undefined, asOwner);
  ok(r.status === 200 && r.body.id === jid && !r.body.project && !/hunter22/.test(JSON.stringify(r.body))
     && r.body.spec?.argv?.[1] === '<redacted>' && r.body.spec.argv[0] === 'echo',
     `...and opens a node's own job by its id, its spec through the redactor (${r.status} ${JSON.stringify(r.body.spec || r.body.error).slice(0, 80)})`);
  r = await call(`/api/v1/jobs?node=${node.id}&n=50`, undefined, asOwner);
  ok((r.body.jobs || []).some(j => j.id === jid), '...and sees it in the listing');
  r = await call(`/api/v1/jobs?id=${jid}`, undefined, asPlain);
  ok(r.status === 404, `...which an account without the grant does not, as for a typo (${r.status})`);
  await call('/api/prefs', { project: 'alpha', diag: false });
  r = await call(`/api/v1/jobs?id=${jid}`, undefined, asOwner);
  ok(r.status === 404, `...nor the owner's session once alpha's grant is off (${r.status})`);
  await call('/api/prefs', { project: 'alpha', diag: true });
  await call('/api/v1/jobs', { action: 'cancel', id: jid });
  // Admin is built in with everything the owner may do since R152 (the
  // operator, 7 Oct), the debug options included; a plain account is not.
  r = await call('/api/diag', {}, asAdmin);
  ok(r.status === 200, `an administrator's session reads it too: admin holds everything the owner does (${r.status} ${r.body.error || ''})`);
  r = await call('/api/diag', {}, asPlain);
  ok(r.status === 403 && /debug grant/.test(r.body.error || ''), `...and a plain account's is refused (${r.body.error})`);
  r = await call('/api/diag', {}, basic('diag.admin', 'diag.admin-pw'));
  ok(r.status === 200, `...as is the administrator with a password, in the dashboard (${r.status})`);
  r = await call('/api/prefs', { project: 'alpha', diag: false }, basic('diag.plain', 'diag.plain-pw'));
  ok(r.status === 403, `a plain account may not change a project's Debug grants (${r.status})`);
  const can = acc => call('/api/status', undefined, basic(acc, `${acc}-pw`)).then(x => x.body?.can?.debug);
  ok(await can('diag.admin') === true && await can('diag.plain') === false,
     'the status gives an administrator the debug options and a plain account none');

  // Everything back as it was found.
  await call('/api/roles', { action: 'remove', name: 'debugger' });
  await call('/api/prefs', { project: 'alpha', diag: wasDiag, log_from: [] });
  await call('/api/settings', { set: { debug_mode: wasDebug } });
  await call('/api/prefs', { project: 'alpha', node: wasNode });
  usersPy('d = u.load(); d["users"].pop("diag.plain", None); d["users"].pop("diag.admin", None); u._save(d)');
  ok(prefsPy('print(p.get("alpha").get("node") or "")') === wasNode,
     `...and what it touched is as it was: alpha's node (${wasNode || 'none'}) and its grants`);
}

await done();
