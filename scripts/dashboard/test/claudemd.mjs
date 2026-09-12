// The environment block: what a project's CLAUDE.md is told, and by whom.
//
// It is prepended to every session on every project, so two things about it
// are worth measuring rather than trusting. First, that what it SAYS about the
// environment is true — it told every session "bb status says which machine
// this is" in four places while that command said nothing of the kind (B98),
// and an instruction that is confidently wrong is worse than a missing one
// because the session stops looking. Second, that a project is only handed the
// parts that apply to it: about a sixth of the file is Android and the dev
// instance, and every project used to pay for both on every conversation.
import { URL, DIR, launch, newPage, ok, done, ready, sleep, refreshUntil } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const BB = fileURLToPath(new globalThis.URL('../../bb', import.meta.url));
const TPL = fileURLToPath(new globalThis.URL('../../../config/templates/project-CLAUDE.md',
                                  import.meta.url));
const base = {
  ...process.env,
  // Never relayed: these cases are about what this copy of bb renders, and a
  // relay would answer from whatever the controller's image happens to carry.
  BB_RELAYED: '1',
  TEMPLATE_MD: TPL,
  WORKSPACE: `${DIR}/ws`,
  DASHBOARD_STATE: `${DIR}/state`,
};
const bb = (args, env = {}) => {
  try {
    return execFileSync('bash', [BB, ...args],
                        { encoding: 'utf8', env: { ...base, ...env } });
  } catch (e) { return String(e.stdout || '') + String(e.stderr || ''); }
};

// ---- which machine am I on ------------------------------------------------
// The question decides whether adb reaches the emulator, whether a plain git
// push works, and whether CI is this machine. Four places in the template send
// a session to `bb status` for the answer.
{
  const asNode = bb(['status'], { BUILDERBOT_ROLE: 'node', BB_NODE: 'testbox' });
  ok(/^== where ==/m.test(asNode),
     'bb status opens by saying where it is running');
  ok(/machine\s+a node, testbox/.test(asNode),
     `...naming the node when it is on one (${
       (asNode.split('\n').find(l => /machine/.test(l)) || 'no machine line').trim()})`);
  ok(/bb git push/.test(asNode),
     '...and what follows from that: pushing on a node goes through bb');

  const asCtl = bb(['status'], { BUILDERBOT_ROLE: 'controller' });
  ok(/machine\s+the controller/.test(asCtl),
     `...and says the controller when it is one (${
       (asCtl.split('\n').find(l => /machine/.test(l)) || 'no machine line').trim()})`);
  ok(/bb nodes/.test(asCtl.split('== versions ==')[0]),
     '...pointing at where a build actually goes from there');

  // The trap this replaced: the only "node" in the old output was Node.js,
  // which reads exactly like an answer to a session looking for one.
  const where = asNode.split('== versions ==')[0];
  ok(!/node\s+v\d/.test(where),
     'the runtime version is not in that block, where it would read as the answer');
}

// ---- a project is handed the parts that apply to it -----------------------
const shapes = [
  ['android and compose', ['build.gradle', 'docker-compose.yml'], true, true],
  ['android alone', ['settings.gradle.kts'], true, false],
  ['android in a subdirectory', ['android/'], true, false],
  ['compose alone', ['compose.yaml'], false, true],
  ['neither', [], false, false],
];
const sizes = {};
for (const [name, files, wantAndroid, wantCompose] of shapes) {
  const d = mkdtempSync(join(tmpdir(), 'cmd-'));
  for (const f of files) {
    if (f.endsWith('/')) mkdirSync(join(d, f), { recursive: true });
    else writeFileSync(join(d, f), 'x');
  }
  bb(['claude-md', '--init', join(d, 'CLAUDE.md')]);
  const txt = readFileSync(join(d, 'CLAUDE.md'), 'utf8');
  sizes[name] = txt.split(/\s+/).length;
  ok(/\n## Android\n/.test(txt) === wantAndroid
     && /\n## The dev instance/.test(txt) === wantCompose,
     `${name}: gets Android=${wantAndroid}, dev instance=${wantCompose} (${
       sizes[name]} words)`);
  // Whatever it got, the file it was just handed must read as current: an
  // --init that renders one thing and a check that expects another is a
  // project that opens every session with an update link it does not need.
  const chk = bb(['claude-md', join(d, 'CLAUDE.md')]);
  ok(/is current/.test(chk),
     `...and reads as current straight after --init (${chk.trim().slice(-40)})`);
  ok(!/BUILDERBOT:IF|BUILDERBOT:END/.test(txt),
     '...with no rendering marker left in what a session reads');
  rmSync(d, { recursive: true, force: true });
}
ok(sizes['neither'] < sizes['android and compose'] - 900,
   `a project with neither is spared both sections (${
     sizes['android and compose']} words down to ${sizes['neither']})`);

// ---- and the sections arrive when the evidence does ------------------------
// Gaining a compose file is ordinary drift: the check notices, and the update
// is the same one press as any other change to the block.
{
  const d = mkdtempSync(join(tmpdir(), 'cmd-'));
  bb(['claude-md', '--init', join(d, 'CLAUDE.md')]);
  ok(!/\n## The dev instance/.test(readFileSync(join(d, 'CLAUDE.md'), 'utf8')),
     'a project with no compose file starts without that section');
  writeFileSync(join(d, 'docker-compose.yml'), 'services: {}\n');
  const chk = bb(['claude-md', join(d, 'CLAUDE.md')]);
  ok(/differs|update/i.test(chk),
     `...and adding one reads as drift, not as a file that is fine (${chk.trim().slice(0, 60)})`);
  bb(['claude-md', '--update', join(d, 'CLAUDE.md')]);
  ok(/\n## The dev instance/.test(readFileSync(join(d, 'CLAUDE.md'), 'utf8')),
     '...which the update then gives it');
  rmSync(d, { recursive: true, force: true });
}

// ---- the project's own notes are never the update's business ---------------
{
  const d = mkdtempSync(join(tmpdir(), 'cmd-'));
  bb(['claude-md', '--init', join(d, 'CLAUDE.md')]);
  const mine = '\n## About this project\n\nMINE, and not the template\'s.\n';
  writeFileSync(join(d, 'CLAUDE.md'),
                readFileSync(join(d, 'CLAUDE.md'), 'utf8') + mine);
  writeFileSync(join(d, 'build.gradle'), 'x');
  bb(['claude-md', '--update', join(d, 'CLAUDE.md')]);
  const after = readFileSync(join(d, 'CLAUDE.md'), 'utf8');
  ok(/MINE, and not the template's\./.test(after) && /\n## Android\n/.test(after),
     'an update that adds a section leaves the project\'s own notes alone');
  rmSync(d, { recursive: true, force: true });
}

// ---- and the server renders the same block bb writes ----------------------
// Two renderers, and this is the one that has to agree: `bb claude-md` writes
// the file, and the server re-renders the template on every poll to decide
// whether a project has drifted. When those disagreed, every project reported
// stale forever and the update link on the row could never clear it — which is
// what happened the first time this was built with the evidence in the code
// instead of in the template.
{
  const browser = await launch();
  const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
  await page.goto(URL);
  await ready(page);
  const P = `${DIR}/ws/mdshape`;
  rmSync(P, { recursive: true, force: true });
  mkdirSync(P, { recursive: true });
  writeFileSync(`${P}/README.md`, 'x\n');
  execFileSync('git', ['-C', P, 'init', '-q', '.'],
               { env: { ...base, GIT_AUTHOR_NAME: 'T', GIT_AUTHOR_EMAIL: 't@x.invalid',
                        GIT_COMMITTER_NAME: 'T', GIT_COMMITTER_EMAIL: 't@x.invalid' } });
  const stale = () => page.evaluate(async () => {
    const r = await fetch('/api/status');
    const p = ((await r.json()).projects || []).find(x => x.name === 'mdshape');
    return (p?.issues || []).some(i => i.action === 'claude-md-update');
  });

  bb(['claude-md', '--init', `${P}/CLAUDE.md`]);
  await refreshUntil(page, () => (state.projects || []).some(p => p.name === 'mdshape'),
                     { timeout: 30000 });
  await sleep(1200);
  ok((await stale()) === false,
     'a file bb just wrote reads as current to the server, not as drift');

  // ...and the same after the evidence arrives, which is the case that pins
  // the two renderings together rather than only the empty one.
  writeFileSync(`${P}/build.gradle`, 'x\n');
  bb(['claude-md', '--update', `${P}/CLAUDE.md`]);
  ok(/\n## Android\n/.test(readFileSync(`${P}/CLAUDE.md`, 'utf8')),
     '...and bb gives it the Android section once there is a gradle file');
  await sleep(1200);
  ok((await stale()) === false,
     '...which the server also reads as current, so the row offers no update');

  rmSync(P, { recursive: true, force: true });

  // ---- a window move, and the one press that undoes it (B93) -------------
  // A minor bump moves the compatibility window, which holds EVERY project at
  // once: sessions ended, Claude button ghosted, until each block is updated.
  // The only control used to be the link on each project's own row, so six
  // projects was six presses. The bell reports them; the bell now fixes them.
  const holds = ['mdheld1', 'mdheld2'];
  for (const name of holds){
    const D = `${DIR}/ws/${name}`;
    rmSync(D, { recursive: true, force: true });
    mkdirSync(D, { recursive: true });
    writeFileSync(`${D}/README.md`, 'x\n');
    execFileSync('git', ['-C', D, 'init', '-q', '.'],
                 { env: { ...base, GIT_AUTHOR_NAME: 'T', GIT_AUTHOR_EMAIL: 't@x.invalid',
                          GIT_COMMITTER_NAME: 'T', GIT_COMMITTER_EMAIL: 't@x.invalid' } });
    bb(['claude-md', '--init', `${D}/CLAUDE.md`]);
    // ...from another window, which is exactly what a bump leaves behind.
    writeFileSync(`${D}/CLAUDE.md`, readFileSync(`${D}/CLAUDE.md`, 'utf8')
      .replace(/BUILDERBOT:ENV:WINDOW \d+\.\d+/, 'BUILDERBOT:ENV:WINDOW 0.1'));
  }
  await refreshUntil(page, () => (state.attention || [])
    .filter(a => a.kind === 'md').length >= 2, { timeout: 40000 });
  await page.click('#bBell');
  await page.waitForSelector('#bellPanel [data-bmdall]', { timeout: 10000 });
  ok(await page.$$eval('#bellPanel [data-bmd]', a => a.length) === 0,
     'several projects held by one window move are one row in the bell, not one each');
  const row = await page.$eval('#bellPanel .bnote.ask.bad', e => e.textContent.replace(/\s+/g, ' '));
  ok(/mdheld1/.test(row) && /mdheld2/.test(row) && /Update all 2/.test(row),
     `...naming them and offering the one press (${row.slice(0, 90)})`);
  await page.click('#bellPanel [data-bmdall]');
  await page.waitForFunction(() => /CLAUDE\.md blocks? updated/.test(
    document.getElementById('toast')?.textContent || ''), null, { timeout: 30000 });
  ok(holds.every(n => /BUILDERBOT:ENV:WINDOW 0\.1/.test(
       readFileSync(`${DIR}/ws/${n}/CLAUDE.md`, 'utf8')) === false),
     '...and one press restamps every one of them');
  for (const n of holds) rmSync(`${DIR}/ws/${n}`, { recursive: true, force: true });

  await done(browser);
}

ok(true, 'done');
