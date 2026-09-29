// A session's view (R35, B156). bb-session builds a mount, PID and IPC
// namespace per session that holds only its own project. The suite has no
// root, so it proves the half that decides everything: the plan. Every path
// `enter` binds, covers or hides is a step of `plan`, which reads the layout
// and changes nothing, and a scratch layout stands in for a node with two
// projects, two accounts and the agent's stores.
import { ok, done, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, symlinkSync, existsSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { userInfo } from 'node:os';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const HELPER = join(REPO, 'nodes', 'bb-session');
const STAGE = '/run/bb-session';
const L = join(DIR, 'viewlayout');
const ws = join(L, 'workspace'), homeRoot = join(L, 'home'), users = join(homeRoot, 'users');
const data = join(L, 'data'), art = join(L, 'artifacts'), runner = join(L, 'runner'), devdata = join(L, 'devdata');
// The scoped toolchain store: the .bb bundle a session and the agent run, and a
// toolchain beside it a build writes to (B157).
const pkg = join(L, 'toolchains', 'linux-x86_64');
const me = 'u_0000abcd', other = 'u_1111abcd';
const myHome = join(users, me);
// Claude Code's transcript folder for a path: every other character a dash.
const slug = p => p.replace(/[^A-Za-z0-9]/g, '-');
const tr = join(ws, '.claude', me, 'projects');
for (const d of [join(ws, 'alpha'), join(ws, 'beta'), join(ws, 'alpha-two'),
                 join(ws, '.worktrees', 'alpha', me), join(ws, '.worktrees', 'beta', me),
                 join(tr, slug(join(ws, 'alpha'))), join(tr, slug(join(ws, 'beta'))),
                 join(tr, slug(join(ws, 'alpha-two'))),
                 join(tr, slug(join(ws, '.worktrees', 'alpha', me))),
                 join(tr, slug(join(ws, '.worktrees', 'alpha-two', me))),
                 join(ws, '.claude', other, 'projects'),
                 join(myHome, '.cache', 'builderbot', 'u', me, 'project', 'alpha'),
                 join(myHome, '.cache', 'builderbot', 'u', me, 'project', 'beta'),
                 join(myHome, '.cache', 'builderbot', 'u', me, 'account'),
                 join(users, other, '.claude'),
                 join(homeRoot, '.cache', 'builderbot', 'machine'),
                 join(homeRoot, '.cache', 'builderbot', 'u', me, 'project', 'gamma'),
                 join(homeRoot, '.claude'), join(homeRoot, '.ssh'), join(homeRoot, '.gradle'),
                 join(homeRoot, '.config', 'gh'), join(homeRoot, '.local', 'share', 'keyrings'),
                 join(data, 'emu'), join(data, 'ci-logs', 'alpha'), join(data, 'ci-logs', 'beta'),
                 join(data, 'jobs'), join(data, 'compose'), join(art, 'alpha'), join(art, 'beta'),
                 join(pkg, '.bb', 'current'), join(pkg, 'jdk'), join(pkg, 'flutter', 'bin', 'cache'),
                 join(homeRoot, '.local', 'bin'),
                 runner, devdata])
  mkdirSync(d, { recursive: true });
writeFileSync(join(homeRoot, '.claude.json'), '{}');
for (const f of ['.bash_history', 'id_somewhere', '.netrc']) writeFileSync(join(homeRoot, f), 'x\n', { mode: 0o600 });
// The shared launcher, in the shape the controller's own node has: a symlink
// in .local/bin pointing at a versioned binary under .local/share/claude. The
// dev VM has the other shape, a plain wrapper script, and the block below
// covers that one; testing only the plain file is how the first version of
// this fix came to do nothing on the box the operator works on.
mkdirSync(join(homeRoot, '.local', 'share', 'claude', 'versions'), { recursive: true });
writeFileSync(join(homeRoot, '.local', 'share', 'claude', 'versions', '2.1.273'), 'BINARY\n', { mode: 0o755 });
symlinkSync(join(homeRoot, '.local', 'share', 'claude', 'versions', '2.1.273'),
            join(homeRoot, '.local', 'bin', 'claude'));
symlinkSync(join(ws, 'beta'), join(ws, 'linked'));
const conf = join(L, 'bb-session.conf');
writeFileSync(conf, [`SESSION_USER=${userInfo().username}`, `WORKSPACE=${ws}`, `HOME_ROOT=${homeRoot}`,
  `DATA_STORE=${data}`, `ARTIFACTS_STORE=${art}`, `TOOLCHAINS_STORE=${pkg}`,
  `RUNNER_DIR=${runner}`, `HIDE=${devdata}`, 'STATE_DIR='].join('\n') + '\n',
  { mode: 0o644 });
// What is at the top of the machine and in its mount table is the box's the
// suite runs on, so the plan is handed a stand-in for each: nothing at all
// here, and a machine of its own further down.
const bare = join(L, 'bare'), noMounts = join(L, 'mounts-none');
mkdirSync(bare, { recursive: true });
writeFileSync(noMounts, '');
process.env.BB_SESSION_ROOT = bare;
process.env.BB_SESSION_MOUNTS = noMounts;

const run = (...args) => {
  try {
    return { code: 0, out: execFileSync(HELPER, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, BB_SESSION_CONF: conf } }) };
  } catch (e) { return { code: e.status, out: `${e.stdout || ''}${e.stderr || ''}` }; }
};
const plan = (over = {}) => {
  const a = { project: 'alpha', account: me, home: myHome, cwd: join(ws, '.worktrees', 'alpha', me), ...over };
  return run('plan', ...Object.entries(a).flatMap(([k, v]) => [`--${k}`, v]));
};

const myCache = join(myHome, '.cache', 'builderbot'), rootCache = join(homeRoot, '.cache', 'builderbot');
// The GPU display's socket (R20): where the machine has /tmp/.X11-unix, it
// is staged before /tmp becomes the session's own and bound back into it.
// Made here when the box has none, since the plan reads the machine.
const x11 = '/tmp/.X11-unix';
const madeX11 = !existsSync(x11) && (() => { try { mkdirSync(x11); return true; } catch { return false; } })();
const got = plan();
const steps = got.code === 0 ? JSON.parse(got.out) : [];
if (madeX11) { try { rmSync(x11, { recursive: true, force: true }); } catch { /* left as found */ } }
ok(!existsSync(x11) && !madeX11 ? true
   : steps.some(x => x[0] === 'bind' && x[1] === x11 && x[2] === `${STAGE}/x11`) && steps.some(x => x[0] === 'bind' && x[1] === `${STAGE}/x11` && x[2] === x11),
   'the X server\'s socket directory is staged and bound back into the session\'s own /tmp');
const has = (...s) => steps.some(x => JSON.stringify(x) === JSON.stringify(s));
const at0 = (...s) => steps.findIndex(x => JSON.stringify(x) === JSON.stringify(s));
const bound = t => steps.some(x => x[0] === 'bind' && x[2] === t);
const hidden = t => steps.some(x => (x[0] === 'hide' || x[0] === 'hidefile') && x[1] === t);
ok(got.code === 0 && steps.length > 10, `bb-session plans a view for a session without making one, as anybody (${got.code}: ${got.out.slice(0, 80)})`);

ok(has('tmpfs', ws, 'mode=0755') && bound(join(ws, 'alpha')) && bound(join(ws, '.worktrees', 'alpha'))
   && bound(join(ws, '.claude', me)) && !bound(join(ws, 'beta')) && !bound(join(ws, 'alpha-two'))
   && !bound(join(ws, '.claude', other)),
   'the projects share in the view holds the project, its worktrees and the account\'s Claude share, and no other project or account');
ok(hidden(join(tr, slug(join(ws, 'beta')))) && hidden(join(tr, slug(join(ws, 'alpha-two'))))
   && hidden(join(tr, slug(join(ws, '.worktrees', 'alpha-two', me))))
   && !hidden(join(tr, slug(join(ws, 'alpha')))) && !hidden(join(tr, slug(join(ws, '.worktrees', 'alpha', me)))),
   '...and the other projects\' transcripts are empty, a project whose name starts another\'s included, while its own stay');
// A project this one reads (prefs.reads) is in the view too, read-only and
// nothing of it but the tree; itself, or a name that is no project, refused.
{
  const r = plan({ reads: 'beta' });
  const rs = r.code === 0 ? JSON.parse(r.out) : [];
  ok(r.code === 0 && rs.some(x => x[0] === 'bindro' && x[1] === `${STAGE}/ws/beta` && x[2] === join(ws, 'beta'))
     && !rs.some(x => x[0] === 'bind' && x[2] === join(ws, 'beta')) && !rs.some(x => x[2] === join(ws, '.worktrees', 'beta')),
     `--reads binds that project's tree into the view read-only, and none of its worktrees (${r.code})`);
  // The account's own conversations on a read project are there to read,
  // read-only, while every other project's stay empty (29 Sep).
  const betaTr = join(tr, slug(join(ws, 'beta')));
  ok(rs.some(x => x[0] === 'bindro' && x[2] === betaTr && x[1] === `${STAGE}/ws/.claude/${me}/projects/${slug(join(ws, 'beta'))}`)
     && !rs.some(x => (x[0] === 'hide') && x[1] === betaTr) && rs.some(x => x[0] === 'hide' && x[1] === join(tr, slug(join(ws, 'alpha-two')))),
     "...and the account's transcripts on that project are bound read-only rather than hidden, the other projects' still hidden");
  const self = plan({ reads: 'alpha' }), none = plan({ reads: 'nowhere' });
  ok(self.code !== 0 && /not a project this one could read/.test(self.out) && none.code !== 0 && /is not a project directory/.test(none.out),
     `...and refuses itself or a name that is no project (${self.out.trim().slice(0, 60)})`);
}
// ...and applying it makes the target under the fresh /workspace before
// the read-only bind, as the writable bind always did: the first session
// with a read project met "mount: No such file or directory" (28 Sep).
{
  const said = execFileSync('python3', ['-c', `
import importlib.machinery, importlib.util, json, os, tempfile
loader = importlib.machinery.SourceFileLoader('bbs', ${JSON.stringify(HELPER)})
m = importlib.util.module_from_spec(importlib.util.spec_from_loader('bbs', loader)); loader.exec_module(m)
calls = []
m._mount = lambda *a: calls.append(a[:2])
root = tempfile.mkdtemp()
src = os.path.join(root, 'src'); os.makedirs(src)
target = os.path.join(root, 'ws', 'hello')
m.apply([('bindro', src, target)], os.getuid(), os.getgid())
# ...and onto a file that is there (the claude binary's link) it makes nothing.
link = os.path.join(root, 'claude'); os.symlink(os.path.join(src, 'x'), link)
m.apply([('bindro', src, link)], os.getuid(), os.getgid())
print(json.dumps({'made': os.path.isdir(target), 'mounts': len(calls), 'onto': calls[0][1] if calls else '', 'link': os.path.islink(link)}))
`], { encoding: 'utf8' }).trim();
  const r = JSON.parse(said);
  ok(r.made && r.mounts === 4 && r.onto.endsWith('/ws/hello') && r.link,
     `a read-only bind makes its target under the view before mounting, as a writable one does, and leaves a file that is there alone (${said})`);
}
ok(has('tmpfs', users, 'mode=0755') && has('bind', `${STAGE}/home`, myHome),
   'the account\'s home is the only home');
// The base home is another's, and every session runs as the account that
// owns it, so its permissions keep nothing back (B378): a session listed
// its .ssh, its shell history and a private key beside them. In the view
// it is new, and holds what a session runs from it and nothing else.
{
  const base = steps.filter(x => String(x[x.length - 1]).startsWith(homeRoot + '/') || x[x.length - 1] === homeRoot);
  const put = base.filter(x => x[0] === 'bindro').map(x => [x[1], x[2]]);
  const kept = ['.local/bin', '.local/share/claude'];
  ok(has('bind', homeRoot, `${STAGE}/base`) && has('tmpfs', homeRoot, 'mode=0755')
     && kept.every(k => put.some(([from, to]) => from === `${STAGE}/base/${k}` && to === join(homeRoot, k)))
     && at0('tmpfs', homeRoot, 'mode=0755') < at0('tmpfs', users, 'mode=0755')
     && at0('tmpfs', homeRoot, 'mode=0755') < at0('tmpfs', rootCache, 'mode=0700,owned'),
     `the base home in the view is new, made before the homes and the caches inside it, and holds the launchers and Claude Code read-only (${
       put.map(p => p[1].slice(homeRoot.length + 1)).join(', ')})`);
  const named = ['.ssh', '.gradle', '.config', '.claude', '.claude.json', '.bash_history', 'id_somewhere', '.netrc', '.local/share/keyrings', '.local/share', '.local'];
  const back = named.filter(n => steps.some(x => x[0].startsWith('bind') && x[x.length - 1] === join(homeRoot, n)));
  ok(back.length === 0 && !steps.some(x => x[0] === 'bindro' && x[1] === homeRoot),
     `...and nothing else of its owner's is put back: no keys, no history, no login, no settings, and no part of .local a session does not run (${back.join(', ') || 'none'})`);
}
ok(has('tmpfs', myCache, 'mode=0700,owned') && bound(join(myCache, 'u', me, 'project', 'alpha')) && bound(join(myCache, 'u', me, 'account'))
   && !bound(join(myCache, 'u', me, 'project', 'beta'))
   && has('tmpfs', rootCache, 'mode=0700,owned') && bound(join(rootCache, 'machine')) && !bound(join(rootCache, 'u', me, 'project', 'gamma')),
   'the cache keeps this project\'s folder, the account\'s and the machine\'s, so no other project\'s token or launcher is there');
ok(has('tmpfs', data, 'mode=0755') && bound(join(data, 'emu')) && bound(join(data, 'ci-logs', 'alpha'))
   && !bound(join(data, 'ci-logs', 'beta')) && !bound(join(data, 'jobs')) && !bound(join(data, 'compose'))
   && bound(join(art, 'alpha')) && !bound(join(art, 'beta')) && hidden(runner) && hidden(devdata),
   'the agent\'s stores keep the emulator, its own CI logs and artifacts; jobs, compose files, the runner and dev data are gone');
ok(has('bindro', pkg, pkg) && !bound(join(pkg, 'jdk')) && !steps.some(x => x[0] === 'bindrw' && x[1] === join(pkg, 'jdk')),
   'the whole toolchain store is read-only in the view, the bundle and every toolchain, so a session cannot plant a command a job or another session runs (B157, B163)');
const at = (...s) => steps.findIndex(x => JSON.stringify(x) === JSON.stringify(s));
const fl = join(pkg, 'flutter');
ok(at('bindro', pkg, pkg) < at('bindrw', fl, fl) && at('bindrw', fl, fl) < at('bindro', join(fl, 'bin'), join(fl, 'bin'))
   && at('bindro', join(fl, 'bin'), join(fl, 'bin')) < at('bindrw', join(fl, 'bin', 'cache'), join(fl, 'bin', 'cache')),
   '...but flutter, which writes its own tree on every run, gets it back, with its bin on PATH still read-only and only bin/cache writable again');
const versions = join(homeRoot, '.local', 'share', 'claude', 'versions');
ok(has('bindro', `${STAGE}/base/.local/share/claude`, join(homeRoot, '.local', 'share', 'claude'))
   && has('bindro', `${STAGE}/base/.local/bin`, join(homeRoot, '.local', 'bin')),
   'the claude binary every account\'s session runs, and the link that names it, are read-only in the view (B157)');
{
  // An account whose home IS the base home has no new home to put them in:
  // they are made read-only where they are, as they always were.
  const own = JSON.parse(plan({ home: homeRoot, cwd: join(ws, 'alpha') }).out || '[]');
  ok(own.some(x => x[0] === 'bindro' && x[1] === versions && x[2] === versions)
     && !own.some(x => x[0] === 'tmpfs' && x[1] === homeRoot),
     '...and where the account\'s home is the base home, that home stays and the binary is made read-only in place');
}
{
  // The OTHER shape, which the dev VM has: a plain wrapper script at
  // .local/bin/claude and no versions directory at all. The file itself is
  // what every account execs there, so it is the file that is bound.
  const alt = join(L, 'althome');
  mkdirSync(join(alt, '.local', 'bin'), { recursive: true });
  writeFileSync(join(alt, '.local', 'bin', 'claude'), '#!/bin/sh\nexec real\n', { mode: 0o755 });
  mkdirSync(join(alt, 'users', me), { recursive: true });
  const altConf = join(L, 'bb-session-plainclaude.conf');
  writeFileSync(altConf, [`SESSION_USER=${userInfo().username}`, `WORKSPACE=${ws}`,
    `HOME_ROOT=${alt}`, `DATA_STORE=${data}`, `ARTIFACTS_STORE=${art}`,
    `TOOLCHAINS_STORE=${pkg}`, `RUNNER_DIR=${runner}`, `HIDE=${devdata}`, 'STATE_DIR='].join('\n') + '\n', { mode: 0o644 });
  const g2 = JSON.parse(execFileSync(HELPER,
    ['plan', '--project', 'alpha', '--account', me, '--home', join(alt, 'users', me),
     '--cwd', join(ws, 'alpha')],
    { encoding: 'utf8', env: { ...process.env, BB_SESSION_CONF: altConf } }));
  ok(g2.some(x => x[0] === 'bindro' && x[1] === `${STAGE}/base/.local/bin` && x[2] === join(alt, '.local', 'bin'))
     && !g2.some(x => x[0] === 'bindro' && x[2] === join(alt, '.local', 'share', 'claude')),
     'a node whose claude is a plain wrapper script has the folder it is in put back read-only, and no versions folder it does not have');
  // ...and one kept anywhere else in that home is put back as the file it is.
  const odd = join(L, 'oddhome');
  mkdirSync(join(odd, '.local', 'bin'), { recursive: true });
  mkdirSync(join(odd, 'tools'), { recursive: true });
  mkdirSync(join(odd, 'users', me), { recursive: true });
  writeFileSync(join(odd, 'tools', 'claude-real'), 'BINARY\n', { mode: 0o755 });
  symlinkSync(join(odd, 'tools', 'claude-real'), join(odd, '.local', 'bin', 'claude'));
  const oddConf = join(L, 'bb-session-oddclaude.conf');
  writeFileSync(oddConf, [`SESSION_USER=${userInfo().username}`, `WORKSPACE=${ws}`,
    `HOME_ROOT=${odd}`, `DATA_STORE=${data}`, `ARTIFACTS_STORE=${art}`,
    `TOOLCHAINS_STORE=${pkg}`, `RUNNER_DIR=${runner}`, `HIDE=${devdata}`, 'STATE_DIR='].join('\n') + '\n', { mode: 0o644 });
  const g3 = JSON.parse(execFileSync(HELPER,
    ['plan', '--project', 'alpha', '--account', me, '--home', join(odd, 'users', me), '--cwd', join(ws, 'alpha')],
    { encoding: 'utf8', env: { ...process.env, BB_SESSION_CONF: oddConf } }));
  ok(g3.some(x => x[0] === 'bindro' && x[1] === `${STAGE}/base/tools/claude-real` && x[2] === join(odd, 'tools', 'claude-real'))
     && !g3.some(x => x[0].startsWith('bind') && x[2] === join(odd, 'tools')),
     'a launcher that points anywhere else in the base home has that one file put back, and not the folder around it');
}
{
  // A file put back into a new home has a file to land on made for it.
  const said = execFileSync('python3', ['-c', `
import importlib.machinery, importlib.util, json, os, tempfile, errno
loader = importlib.machinery.SourceFileLoader('bbs', ${JSON.stringify(HELPER)})
m = importlib.util.module_from_spec(importlib.util.spec_from_loader('bbs', loader)); loader.exec_module(m)
calls = []
m._mount = lambda *a: calls.append(a[:2])
root = tempfile.mkdtemp()
src = os.path.join(root, 'claude-real'); open(src, 'w').close()
target = os.path.join(root, 'home', 'tools', 'claude-real')
m.apply([('bindro', src, target)], os.getuid(), os.getgid())
# A mount that is gone already is let go without a word; any other failure is one.
def gone(name, *a):
    raise OSError(errno.EINVAL, 'not mounted')
def busy(name, *a):
    raise OSError(errno.EPERM, 'no')
m._call = gone
m.apply([('letgo', '/nowhere')], os.getuid(), os.getgid())
m._call = busy
try:
    m.apply([('letgo', '/nowhere')], os.getuid(), os.getgid()); held = False
except OSError:
    held = True
print(json.dumps({'file': os.path.isfile(target), 'mounts': len(calls), 'held': held}))
`], { encoding: 'utf8' }).trim();
  const r = JSON.parse(said);
  ok(r.file && r.mounts === 2 && r.held,
     `a file bound into a new home gets a file made to land on; a mount already gone is let go quietly and any other failure stops the view (${said})`);
}
{
  // No TOOLCHAINS_STORE (an older agent's conf, before B157): no bundle bind at
  // all, which leaves the store as it was rather than failing the view.
  const noStore = join(L, 'bb-session-nostore.conf');
  writeFileSync(noStore, [`SESSION_USER=${userInfo().username}`, `WORKSPACE=${ws}`, `HOME_ROOT=${homeRoot}`,
    `DATA_STORE=${data}`, `ARTIFACTS_STORE=${art}`, `RUNNER_DIR=${runner}`, `HIDE=${devdata}`, 'STATE_DIR='].join('\n') + '\n', { mode: 0o644 });
  const g = (() => { try { return { code: 0, out: execFileSync(HELPER,
    ['plan', '--project', 'alpha', '--account', me, '--home', myHome, '--cwd', join(ws, '.worktrees', 'alpha', me)],
    { encoding: 'utf8', env: { ...process.env, BB_SESSION_CONF: noStore } }) };
  } catch (e) { return { code: e.status, out: `${e.stdout || ''}${e.stderr || ''}` }; } })();
  // No BUNDLE bind. The launcher's is planned either way: it is read off the
  // home root, which every conf carries, so an older agent's node gets that
  // half of B157 without being updated.
  ok(g.code === 0 && !JSON.parse(g.out).some(x => x[0] === 'bindro' && x[1].startsWith(pkg)),
     '...and a conf without TOOLCHAINS_STORE (an agent from before B157) plans no bundle bind rather than failing');
  ok(JSON.parse(g.out).some(x => x[0] === 'bindro' && x[1] === `${STAGE}/base/.local/share/claude`),
     '...while the shared launcher is still made read-only there, since that is read off the home root');
}
ok(has('tmpfs', '/tmp', 'mode=1777') && steps[0][0] === 'private' && steps[1][0] === 'proc'
   && steps[steps.length - 1][0] === 'detach',
   'the view starts private with its own /proc, gets its own /tmp, and lets the staging copy of the machine go last');
// What Claude Code keeps in /tmp for a conversation outlives a restart of
// the session (B376): /tmp is made new with every start, and a session
// started again on the same conversation after a controller update found
// its scratchpad empty, twice in a day. The launcher makes a folder for it
// in the project's cache, and the view binds that over /tmp/claude-<uid>.
{
  const uid = userInfo().uid;
  const scratch = join(myCache, 'u', me, 'project', 'alpha', 'scratch');
  ok(!steps.some(x => x[2] === `/tmp/claude-${uid}`), 'with no folder made for it, /tmp is the session\'s own and nothing more');
  mkdirSync(scratch, { recursive: true });
  const kept = JSON.parse(plan().out);
  const at = kept.findIndex(x => x[0] === 'bind' && x[2] === `/tmp/claude-${uid}`);
  ok(at > kept.findIndex(x => x[0] === 'tmpfs' && x[1] === '/tmp') && at < kept.length - 1
     && kept[at][1].startsWith(`${STAGE}/cache`) && kept[at][1].endsWith(`/u/${me}/project/alpha/scratch`),
     `the conversation's folder in the project's cache is bound over /tmp/claude-${uid}, after /tmp is made (${JSON.stringify(kept[at] || null)})`);
  rmSync(scratch, { recursive: true, force: true });
  symlinkSync(join(ws, 'beta'), scratch);
  ok(!JSON.parse(plan().out).some(x => x[2] === `/tmp/claude-${uid}`),
     '...and a link in its place is not followed: nothing is bound, and /tmp stays as it was');
  rmSync(scratch, { force: true });
}
{
  const firstCover = steps.findIndex(x => x[0] === 'tmpfs' && x[1] === ws);
  const lastStage = Math.max(...steps.map((x, i) => (x[0] === 'bind' && x[2].startsWith(STAGE + '/')) ? i : -1));
  ok(lastStage < firstCover, 'everything a cover would hide is bound aside before the first cover');
}

// The rest of the machine (B378). The view used to cover what it was told to
// (the projects share, the two stores, what HIDE named) and show the rest
// as the node has it: on the dev node a session on a project that reads
// nothing listed the other projects' container data and build caches, and
// on the operator's own a session listed the dev instance's projects, every
// share, and the base home with its keys. Now the view is built from what a
// session is given, and what is not the system's own is out.
{
  const M = join(DIR, 'viewmachine');
  const mws = join(M, 'workspace'), mhome = join(M, 'home', 'builder'), mstate = join(M, 'var', 'lib', 'builderbot');
  const share = join(M, 'mnt', 'bbdata'), mstore = join(share, 'toolchains', 'linux-x86_64');
  const mdata = join(share, 'data'), mart = join(share, 'artifacts');
  for (const d of [join(mws, 'alpha'), join(mws, 'beta'), join(mhome, 'users', me), join(mhome, '.local', 'bin'),
                   join(mstate, 'cache', 'beta'), join(mstate, 'agent', 'tools'), join(mstate, 'runner'), join(mstate, 'packages'),
                   join(share, 'appdata', 'beta', 'db'), join(mstore, 'jdk'), join(share, 'toolchains', 'shared', 'android'),
                   join(share, 'toolchains', 'windows-x86_64'), join(mdata, 'emu'), join(mdata, 'ci-logs', 'alpha'),
                   join(mart, 'alpha'), join(M, 'mnt', 'packages', 'x'), join(M, 'mnt', 'media', 'films'), join(M, 'mnt', 'media', 'private'),
                   join(M, 'auxiliary', 'x'), join(M, 'workspace-dev', 'web'), join(M, 'devdata'), join(M, 'made-by-hand'),
                   join(M, 'etc'), join(M, 'usr', 'bin'), join(M, 'opt', 'tool'), join(M, 'srv', 'www'), join(M, 'lost+found')])
    mkdirSync(d, { recursive: true });
  symlinkSync('usr/bin', join(M, 'bin'));
  writeFileSync(join(M, 'swap.img'), '');
  const mounts = join(M, 'mountinfo');
  const line = (n, at, kind, from) => `${n} 1 0:${n} / ${at} rw,relatime shared:${n} - ${kind} ${from} rw`;
  writeFileSync(mounts, [line(20, M, 'ext4', '/dev/vda2'), line(21, join(M, 'proc'), 'proc', 'proc'),
    line(30, mws, 'nfs4', 'host:/projects'), line(31, share, 'nfs4', 'host:/bbdata'),
    line(32, join(share, 'appdata'), 'nfs4', 'host:/appdata'), line(33, join(M, 'mnt', 'packages'), 'nfs4', 'host:/packages'),
    line(34, join(M, 'auxiliary'), 'nfs4', 'host:/auxiliary'), line(35, join(M, 'workspace-dev'), 'nfs4', 'host:/dev-projects'),
    line(36, join(M, 'devdata'), 'nfs4', 'host:/devdata'), line(37, join(M, 'mnt', 'media'), 'ext4', '/dev/sdb1'),
    line(38, join(M, 'mnt', 'with\\040space'), 'ext4', '/dev/sdc1'), line(41, join(M, 'gone-stale'), 'nfs4', 'host:/gone'),
    line(39, join(mstate, 'packages'), 'nfs4', 'host:/packages'), line(40, join(M, 'opt', 'tool'), 'ext4', '/dev/sdd1')].join('\n') + '\n');
  mkdirSync(join(M, 'mnt', 'with space'), { recursive: true });
  const mconf = join(M, 'bb-session.conf');
  writeFileSync(mconf, [`SESSION_USER=${userInfo().username}`, `WORKSPACE=${mws}`, `HOME_ROOT=${mhome}`,
    `DATA_STORE=${mdata}`, `ARTIFACTS_STORE=${mart}`, `TOOLCHAINS_STORE=${mstore}`,
    `RUNNER_DIR=${join(mstate, 'runner')}`, `HIDE=${join(M, 'devdata')}`, `STATE_DIR=${mstate}`].join('\n') + '\n', { mode: 0o644 });
  const on = (...more) => {
    try {
      return { code: 0, out: execFileSync(HELPER, ['plan', '--project', 'alpha', '--account', me,
        '--home', join(mhome, 'users', me), '--cwd', join(mws, 'alpha'), ...more],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, BB_SESSION_CONF: mconf, BB_SESSION_ROOT: M, BB_SESSION_MOUNTS: mounts } }) };
    } catch (e) { return { code: e.status, out: `${e.stdout || ''}${e.stderr || ''}` }; }
  };
  const r = on();
  const st = r.code === 0 ? JSON.parse(r.out) : [];
  const ix = (...s) => st.findIndex(x => JSON.stringify(x) === JSON.stringify(s));
  const is = (...s) => ix(...s) >= 0;
  const mnt = join(M, 'mnt');
  ok(r.code === 0 && is('tmpfs', mnt, 'mode=0755') && is('tmpfs', mstate, 'mode=0755')
     && ['auxiliary', 'workspace-dev', 'devdata', 'made-by-hand', 'srv'].every(n => is('hide', join(M, n))),
     `what holds one of the view's own places is covered so that place can be put back, and what holds none is hidden whole: a share, the dev instance's projects, a directory made by hand (${r.code}: ${r.out.slice(0, 80)})`);
  ok(!st.some(x => ['etc', 'usr', 'opt', 'lost+found', 'bin', 'swap.img', 'home', 'var'].some(n => x[x.length - 1] === join(M, n)))
     && !is('hide', mws) && st.filter(x => x[0] === 'tmpfs' && x[1] === mws).length === 1,
     '...while the system\'s own names, a link and a file at the top are left as they are, and the projects share is covered once, by its own rule');
  const back = st.filter(x => x[0].startsWith('bind') && (String(x[2]).startsWith(mnt + '/') || String(x[2]).startsWith(mstate + '/'))).map(x => x[2]);
  ok(is('bindro', `${STAGE}/store`, mstore) && is('bind', mstore, `${STAGE}/store`)
     && is('tmpfs', mdata, 'mode=0755') && is('bind', `${STAGE}/data/ci-logs/alpha`, join(mdata, 'ci-logs', 'alpha'))
     && is('bind', `${STAGE}/artifacts/alpha`, join(mart, 'alpha'))
     && is('bind', join(share, 'toolchains', 'shared'), `${STAGE}/store-shared`)
     && is('bindro', `${STAGE}/store-shared`, join(share, 'toolchains', 'shared'))
     && !back.some(b => /appdata|packages|media|cache|agent|runner|windows/.test(b.slice(M.length))),
     `inside the covers the toolchain store, what every scope of it shares (the system images it links to) and this project's part of the two stores are put back, and nothing of another project's container data, the build caches, the agent's tools, another machine's toolchains or a share nobody named (${
       back.map(b => b.slice(M.length)).join(' ')})`);
  ok(ix('bind', mstore, `${STAGE}/store`) < ix('tmpfs', mnt, 'mode=0755') && ix('tmpfs', mnt, 'mode=0755') < ix('tmpfs', mws, 'mode=0755')
     && ix('tmpfs', mnt, 'mode=0755') < ix('bindro', `${STAGE}/store`, mstore) && ix('tmpfs', mstate, 'mode=0755') < ix('tmpfs', mdata, 'mode=0755'),
     '...each bound aside before its cover and put back after it');
  // The runner's folder and what HIDE names are out of sight already:
  // under a cover there is nothing to mount on, and the view would not start.
  ok(!is('hide', join(mstate, 'runner')) && st.filter(x => x[0] === 'hide' && x[1] === join(M, 'devdata')).length === 1,
     'a folder the layout names to hide is hidden once, and not at all where a cover has taken it');
  const let_ = st.filter(x => x[0] === 'letgo').map(x => x[1]);
  ok(JSON.stringify(let_.slice().sort()) === JSON.stringify([join(M, 'auxiliary'), join(M, 'devdata'), share, join(M, 'mnt', 'media'),
       join(M, 'mnt', 'packages'), join(M, 'mnt', 'with space'), join(mstate, 'packages'), join(M, 'workspace-dev'),
       join(M, 'gone-stale')].sort())
     && let_.every(m => ix('letgo', m) < ix('tmpfs', mnt, 'mode=0755') && ix('letgo', m) > ix('bind', mstore, `${STAGE}/store`)),
     `the mounts inside them are let go, the topmost of each, one with a space in its name and one at the top that nothing can read any more, so the mount table names no export either; the machine's own and the projects share stay (${
       let_.map(m => m.slice(M.length)).join(' ')})`);

  // A place the project is set to see (its settings, --sees): inside a
  // cover it is put back, at the top it is left as the node has it.
  const films = join(M, 'mnt', 'media', 'films'), dev = join(M, 'workspace-dev');
  const s = on('--sees', films, '--sees', dev, '--sees', join(M, 'mnt', 'not-on-this-node'));
  const ss = s.code === 0 ? JSON.parse(s.out) : [];
  const six = (...a) => ss.findIndex(x => JSON.stringify(x) === JSON.stringify(a));
  ok(s.code === 0 && six('bind', films, `${STAGE}/sees0`) >= 0 && six('bind', `${STAGE}/sees0`, films) > six('tmpfs', mnt, 'mode=0755')
     && six('bind', films, `${STAGE}/sees0`) < six('tmpfs', mnt, 'mode=0755')
     && !ss.some(x => x[x.length - 1] === join(M, 'mnt', 'media', 'private') || x[x.length - 1] === join(M, 'mnt', 'media')
                      && x[0] !== 'letgo'),
     `a place the project is set to see is put back inside the cover, and what is beside it is not (${s.code}: ${s.out.slice(0, 80)})`);
  ok(!ss.some(x => x[x.length - 1] === dev) && ss.some(x => x[0] === 'hide' && x[1] === join(M, 'auxiliary'))
     && !ss.some(x => String(x[x.length - 1]).includes('not-on-this-node')),
     '...one at the top of the machine is left whole, mounted as the node has it, the rest still hidden; and one this node does not have is passed over');
  const no = [[join(M, 'etc'), 'the system\'s'], [join(mws, 'beta'), 'another project'], [mhome, 'the base home'],
              [join(mstate, 'cache'), 'the agent\'s'], [mnt, 'what holds the stores'], [join(share, 'data'), 'a store'],
              [`${M}/mnt/media/../../made-by-hand`, 'a path that climbs'], ['relative/path', 'a relative path'],
              [join(M, 'mnt', 'with space'), 'a name with a space']]
    .map(([p, what]) => [on('--sees', p), what]);
  const let2 = no.filter(([x]) => !(x.code === 2 && /not a place a project could be shown/.test(x.out))).map(([x, what]) => `${what}: ${x.code}`);
  ok(let2.length === 0, `--sees refuses ${no.map(x => x[1]).join(', ')}${let2.length ? ` (not: ${let2.join(' | ')})` : ''}`);
}

const refusals = [
  [plan({ cwd: join(ws, 'alpha', '..', 'beta') }), /not inside alpha/, 'a working directory that climbs out of the project'],
  [plan({ home: join(users, other) }), /is not u_0000abcd's home/, 'another account\'s home'],
  [plan({ project: 'linked', cwd: join(ws, 'linked') }), /not a project directory/, 'a project that is a link to another'],
  [plan({ project: '../beta' }), /not a project name/, 'a project name with a path in it'],
  [plan({ account: 'nobody' }), /names no account/, 'a session with no account'],
];
const bad = refusals.filter(([r, re]) => !(r.code === 2 && re.test(r.out))).map(([r, , what]) => `${what}: ${r.code} ${r.out.slice(0, 60)}`);
ok(bad.length === 0, `the plan refuses ${refusals.map(r => r[2]).join('; ')}${bad.length ? ` (not: ${bad.join(' | ')})` : ''}`);

// The shape a real node has (found on the dev VM): an account's home links
// .cache to the base home's, so its cache and the machine's are one folder.
// That folder is covered once, keeping what either needed; covering it twice
// buried the project's own folder under the second cover.
{
  const linked = 'u_2222abcd', linkedHome = join(users, linked);
  mkdirSync(linkedHome, { recursive: true });
  symlinkSync(join(homeRoot, '.cache'), join(linkedHome, '.cache'));
  mkdirSync(join(rootCache, 'u', linked, 'project', 'alpha'), { recursive: true });
  const r = plan({ account: linked, home: linkedHome, cwd: join(ws, 'alpha') });
  const st = r.code === 0 ? JSON.parse(r.out) : [];
  const covers = st.filter(x => x[0] === 'tmpfs' && x[1].endsWith('/.cache/builderbot'));
  const binds = st.filter(x => x[0] === 'bind' && x[2].startsWith(rootCache + '/')).map(x => x[2].slice(rootCache.length + 1));
  ok(r.code === 0 && covers.length === 1 && covers[0][1] === rootCache
     && binds.includes(`u/${linked}/project/alpha`) && binds.includes('machine')
     && !binds.some(b => b.endsWith('/project/gamma')),
     `an account whose .cache links to the base home's gets that one folder covered once, keeping this project's and the machine's (${covers.length} cover, kept ${binds.join(', ')})`);
  const planted = 'u_3333abcd', plantedHome = join(users, planted);
  mkdirSync(join(plantedHome, '.cache'), { recursive: true });
  symlinkSync(rootCache, join(plantedHome, '.cache', 'builderbot'));
  const refused = plan({ account: planted, home: plantedHome, cwd: join(ws, 'alpha') });
  ok(refused.code === 2 && /is not a directory, so the view could not leave other projects out/.test(refused.out),
     `...and a cache that is itself a link is refused, never left untrimmed with other projects' tokens in it (${refused.out.trim().slice(0, 60)})`);
}

// A network of its own (R79). Where the agent has turned it on, the view
// also puts the agent's resolver file over the node's (whose resolver sits on
// the node's loopback, out of a namespace of its own's reach) and covers the
// agent's folder, which says which project every other session's address is.
// Off, or with an older layout file, the plan is the one it always was.
{
  const netConf = join(L, 'bb-session-net.conf');
  const withNet = (extra) => {
    writeFileSync(netConf, [`SESSION_USER=${userInfo().username}`, `WORKSPACE=${ws}`, `HOME_ROOT=${homeRoot}`,
      `DATA_STORE=${data}`, `ARTIFACTS_STORE=${art}`, `TOOLCHAINS_STORE=${pkg}`,
      `RUNNER_DIR=${runner}`, `HIDE=${devdata}`, 'STATE_DIR=', ...extra].join('\n') + '\n', { mode: 0o644 });
    try {
      return { code: 0, out: execFileSync(HELPER, ['plan', '--project', 'alpha', '--account', me, '--home', myHome,
        '--cwd', join(ws, 'alpha')], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, BB_SESSION_CONF: netConf } }) };
    } catch (e) { return { code: e.status, out: `${e.stdout || ''}${e.stderr || ''}` }; }
  };
  const on = withNet(['SESSION_NET=on', 'SESSION_NET_CIDR=10.231.0.0/16']);
  const st = on.code === 0 ? JSON.parse(on.out) : [];
  const at = (k, t) => st.findIndex(x => x[0] === k && x[x.length - 1] === t);
  const resolv = at('bindfile', '/etc/resolv.conf'), hid = st.findIndex(x => x[0] === 'hide' && x[1] === '/run/bb-session-net');
  ok(on.code === 0 && resolv > 0 && st[resolv][1] === '/run/bb-session-net/resolv.conf' && hid > resolv
     && st[st.length - 1][0] === 'detach',
     `with the session network on, the view takes the agent's resolver file and then covers the agent's folder (${JSON.stringify(st[resolv] || on.out.slice(0, 80))})`);
  ok(!steps.some(x => x[0] === 'bindfile' || (x[0] === 'hide' && x[1] === '/run/bb-session-net')),
     '...and without it, neither: a layout file from before the setting plans what it always did');
  const badRange = withNet(['SESSION_NET=on', 'SESSION_NET_CIDR=10.231.0.0/30']);
  ok(badRange.code === 2 && /not a range a session can be addressed from/.test(badRange.out),
     `a range too small to address sessions from is refused rather than half used (${badRange.out.trim().slice(0, 70)})`);
  const net = run('check-net');
  ok(net.code === 2 && /runs as root/.test(net.out),
     `check-net, the agent's question before it offers the setting, is root's (${net.out.trim().slice(0, 40)})`);
}

const asMe = run('enter', '--project', 'alpha', '--account', me, '--home', myHome, '--cwd', join(ws, 'alpha'),
                 '--env', join(myCache, 'project', 'alpha', 'session.env'), '--', 'true');
const checked = run('check');
ok(asMe.code === 2 && /as root, through sudo/.test(asMe.out) && checked.code === 2 && /runs as root/.test(checked.out),
   `enter and check refuse anybody but root (${asMe.out.trim().slice(0, 50)} | ${checked.out.trim().slice(0, 40)})`);

await done(null);
