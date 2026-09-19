// State an earlier build wrote under names this one no longer uses, moved
// once at startup (renames.py): the operator's roadmap and open tabs come
// across under the new names rather than being left where nothing reads
// them. Run against a scratch state of its own, twice, since it runs on
// every start.
import { ok, done, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const HERE = new globalThis.URL('..', import.meta.url).pathname;
const st = join(DIR, 'renames-state');
mkdirSync(st, { recursive: true });
writeFileSync(join(st, 'todos.json'), JSON.stringify({
  projects: { alpha: [{ id: 1, text: 'keep me' }] },
  unsaved: { alpha: { todo: true, memory: false } },
  bump: { alpha: { todo: 7, memory: 2 } },
  seen: { alpha: { u_00000001: { todo: 5, memory: 2 } } },
}));
writeFileSync(join(st, 'tabs.json'), JSON.stringify({ users: { u_00000001: {
  tabs: [{ id: 't1', kind: 'todo', arg: 'alpha', label: 'Notebook: alpha' },
         { id: 't2', kind: 'term', arg: 'shell', label: 'sh' },
         { id: 't3', kind: 'packages', arg: '__packages', label: 'packages' }], panes: ['t1', null] } } }));
writeFileSync(join(st, 'pkg-versions.json'), JSON.stringify({ jdk: '21' }));
const run = () => execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("r", ${JSON.stringify(join(HERE, 'renames.py'))})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps(m.run(${JSON.stringify(st)})))`], { encoding: 'utf8' }).trim();

const first = JSON.parse(run());
const road = JSON.parse(readFileSync(join(st, 'roadmap.json'), 'utf8'));
ok(!existsSync(join(st, 'todos.json')) && road.projects.alpha[0].text === 'keep me',
   'the roadmap file comes across under its new name, items and all');
ok(road.unsaved.alpha.roadmap === true && road.bump.alpha.roadmap === 7
   && road.seen.alpha.u_00000001.roadmap === 5 && !('todo' in road.bump.alpha),
   '...with its kind keys renamed, so no session is told of changes it has seen');
const tabs = JSON.parse(readFileSync(join(st, 'tabs.json'), 'utf8')).users.u_00000001.tabs;
ok(tabs[0].kind === 'notebook' && tabs[1].kind === 'term' && tabs[2].kind === 'toolchains',
   'open notebook and toolchain tabs keep their places under their new kinds');
ok(JSON.parse(readFileSync(join(st, 'toolchain-versions.json'), 'utf8')).jdk === '21' && !existsSync(join(st, 'pkg-versions.json')),
   'the toolchain versions last checked come across');
ok(JSON.stringify(first) === '["roadmap","versions","tabs"]', `it says what it moved (${first})`);
ok(run() === '[]', 'and a second start moves nothing');

await done();
