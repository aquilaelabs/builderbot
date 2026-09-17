// A session's view (R35, B156). bb-session builds a mount, PID and IPC
// namespace per session that holds only its own project. The suite has no
// root, so it proves the half that decides everything: the plan. Every path
// `enter` binds, covers or hides is a step of `plan`, which reads the layout
// and changes nothing, and a scratch layout stands in for a node with two
// projects, two accounts and the agent's stores.
import { ok, done, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, symlinkSync } from 'node:fs';
import { join } from 'node:path';
import { userInfo } from 'node:os';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const HELPER = join(REPO, 'nodes', 'bb-session');
const STAGE = '/run/bb-session';
const L = join(DIR, 'viewlayout');
const ws = join(L, 'workspace'), homeRoot = join(L, 'home'), users = join(homeRoot, 'users');
const data = join(L, 'data'), art = join(L, 'artifacts'), runner = join(L, 'runner'), devdata = join(L, 'devdata');
// The scoped packages store: the .bb bundle a session and the agent run, and a
// toolchain beside it a build writes to (B157).
const pkg = join(L, 'packages', 'linux-x86_64');
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
                 join(pkg, '.bb', 'current'), join(pkg, 'jdk'),
                 join(homeRoot, '.local', 'bin'),
                 runner, devdata])
  mkdirSync(d, { recursive: true });
writeFileSync(join(homeRoot, '.claude.json'), '{}');
// The shared launcher: every account's ~/.local is a link to the base home's,
// so this one file is what every session on the node execs.
writeFileSync(join(homeRoot, '.local', 'bin', 'claude'), '#!/bin/sh\n', { mode: 0o755 });
symlinkSync(join(ws, 'beta'), join(ws, 'linked'));
const conf = join(L, 'bb-session.conf');
writeFileSync(conf, [`SESSION_USER=${userInfo().username}`, `WORKSPACE=${ws}`, `HOME_ROOT=${homeRoot}`,
  `DATA_STORE=${data}`, `ARTIFACTS_STORE=${art}`, `PACKAGES_STORE=${pkg}`,
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
const got = plan();
const steps = got.code === 0 ? JSON.parse(got.out) : [];
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
ok(has('bindro', join(pkg, '.bb'), join(pkg, '.bb'))
   && !steps.some(x => x[0] === 'bindro' && x[1] === join(pkg, 'jdk'))
   && !bound(join(pkg, '.bb')),
   'the packages bundle is read-only in the view so a session cannot rewrite the bb the agent and other sessions run, while the toolchains beside it stay writable for a build (B157)');
ok(has('bindro', join(homeRoot, '.local', 'bin', 'claude'), join(homeRoot, '.local', 'bin', 'claude'))
   && !steps.some(x => x[0] === 'bindro' && x[1] === join(homeRoot, '.local', 'bin')),
   'the claude every account\'s session runs is read-only in the view, since .local is shared between homes, while the rest of .local/bin stays writable for a pip --user install (B157)');
{
  // No PACKAGES_STORE (an older agent's conf, before B157): no bundle bind at
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
     '...and a conf without PACKAGES_STORE (an agent from before B157) plans no bundle bind rather than failing');
  ok(JSON.parse(g.out).some(x => x[0] === 'bindro' && x[1] === join(homeRoot, '.local', 'bin', 'claude')),
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

const asMe = run('enter', '--project', 'alpha', '--account', me, '--home', myHome, '--cwd', join(ws, 'alpha'),
                 '--env', join(myCache, 'project', 'alpha', 'session.env'), '--', 'true');
const checked = run('check');
ok(asMe.code === 2 && /as root, through sudo/.test(asMe.out) && checked.code === 2 && /runs as root/.test(checked.out),
   `enter and check refuse anybody but root (${asMe.out.trim().slice(0, 50)} | ${checked.out.trim().slice(0, 40)})`);

await done(null);
