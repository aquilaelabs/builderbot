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
                 join(homeRoot, '.claude'),
                 join(data, 'emu'), join(data, 'ci-logs', 'alpha'), join(data, 'ci-logs', 'beta'),
                 join(data, 'jobs'), join(data, 'compose'), join(art, 'alpha'), join(art, 'beta'),
                 join(pkg, '.bb', 'current'), join(pkg, 'jdk'), join(pkg, 'flutter', 'bin', 'cache'),
                 join(homeRoot, '.local', 'bin'),
                 runner, devdata])
  mkdirSync(d, { recursive: true });
writeFileSync(join(homeRoot, '.claude.json'), '{}');
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
  `RUNNER_DIR=${runner}`, `HIDE=${devdata}`].join('\n') + '\n',
  { mode: 0o644 });

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
ok(has('tmpfs', users, 'mode=0755') && has('bind', `${STAGE}/home`, myHome) && hidden(join(homeRoot, '.claude'))
   && hidden(join(homeRoot, '.claude.json')),
   'the account\'s home is the only home, and the base home\'s Claude login and history are out of sight');
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
const last = at('bindro', homeRoot, homeRoot);
ok(last > 0 && last > at('bind', `${STAGE}/home`, myHome) && last > at('tmpfs', users, 'mode=0755')
   && steps.slice(last + 1).every(x => !String(x[x.length - 1]).startsWith(homeRoot + '/')),
   'and the base home is read-only, bound last so the account\'s own home under users/ and everything hidden in it keep their own mounts');
const versions = join(homeRoot, '.local', 'share', 'claude', 'versions');
ok(has('bindro', versions, versions),
   'the claude binary every account\'s session runs is read-only in the view (B157)');
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
    `TOOLCHAINS_STORE=${pkg}`, `RUNNER_DIR=${runner}`, `HIDE=${devdata}`].join('\n') + '\n', { mode: 0o644 });
  const g2 = JSON.parse(execFileSync(HELPER,
    ['plan', '--project', 'alpha', '--account', me, '--home', join(alt, 'users', me),
     '--cwd', join(ws, 'alpha')],
    { encoding: 'utf8', env: { ...process.env, BB_SESSION_CONF: altConf } }));
  ok(g2.some(x => x[0] === 'bindro' && x[1] === join(alt, '.local', 'bin', 'claude')),
     'a node whose claude is a plain wrapper script has that file made read-only instead');
}
{
  // No TOOLCHAINS_STORE (an older agent's conf, before B157): no bundle bind at
  // all, which leaves the store as it was rather than failing the view.
  const noStore = join(L, 'bb-session-nostore.conf');
  writeFileSync(noStore, [`SESSION_USER=${userInfo().username}`, `WORKSPACE=${ws}`, `HOME_ROOT=${homeRoot}`,
    `DATA_STORE=${data}`, `ARTIFACTS_STORE=${art}`, `RUNNER_DIR=${runner}`, `HIDE=${devdata}`].join('\n') + '\n', { mode: 0o644 });
  const g = (() => { try { return { code: 0, out: execFileSync(HELPER,
    ['plan', '--project', 'alpha', '--account', me, '--home', myHome, '--cwd', join(ws, '.worktrees', 'alpha', me)],
    { encoding: 'utf8', env: { ...process.env, BB_SESSION_CONF: noStore } }) };
  } catch (e) { return { code: e.status, out: `${e.stdout || ''}${e.stderr || ''}` }; } })();
  // No BUNDLE bind. The launcher's is planned either way: it is read off the
  // home root, which every conf carries, so an older agent's node gets that
  // half of B157 without being updated.
  ok(g.code === 0 && !JSON.parse(g.out).some(x => x[0] === 'bindro' && x[1].startsWith(pkg)),
     '...and a conf without TOOLCHAINS_STORE (an agent from before B157) plans no bundle bind rather than failing');
  ok(JSON.parse(g.out).some(x => x[0] === 'bindro' && x[1] === versions),
     '...while the shared launcher is still made read-only there, since that is read off the home root');
}
ok(has('tmpfs', '/tmp', 'mode=1777') && steps[0][0] === 'private' && steps[1][0] === 'proc'
   && steps[steps.length - 1][0] === 'detach',
   'the view starts private with its own /proc, gets its own /tmp, and lets the staging copy of the machine go last');
{
  const firstCover = steps.findIndex(x => x[0] === 'tmpfs' && x[1] === ws);
  const lastStage = Math.max(...steps.map((x, i) => (x[0] === 'bind' && x[2].startsWith(STAGE + '/')) ? i : -1));
  ok(lastStage < firstCover, 'everything a cover would hide is bound aside before the first cover');
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
      `RUNNER_DIR=${runner}`, `HIDE=${devdata}`, ...extra].join('\n') + '\n', { mode: 0o644 });
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
