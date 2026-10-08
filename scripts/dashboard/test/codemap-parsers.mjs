// bb map against real parsers (roadmap R158): what the map says about this
// tree, and about small trees in the languages babel and python cannot
// read, checked against babel's parse of every .js and .mjs here and the
// page's inline scripts, against python's own ast for every .py, and
// against answers written by hand for TypeScript, JSX, Kotlin, shell, C and
// PHP. A scanner regression is a red check here, rather than a gate that
// quietly skipped the suite it needed (8 Oct: run by hand over thirteen
// projects, this found some twenty ways the map read code wrong).
// No browser. Babel is the one inside Playwright's bundle; without it the
// babel half says it was skipped, never that it passed.
import { ok, done, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { createRequire } from 'node:module';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const CODEMAP = `${REPO}/scripts/lib/codemap.py`;
const build = root => {
  execFileSync('python3', [CODEMAP, '--root', root, 'build'], { encoding: 'utf8' });
  return JSON.parse(readFileSync(join(root, '.bb-map', 'map3.json'), 'utf8'));
};
const show = xs => xs.slice(0, 6).map(x => JSON.stringify(x)).join(' ');

// ---- babel, if the bundle is there --------------------------------------------
let babel = null;
for (const base of (process.env.NODE_PATH || '').split(':').filter(Boolean)) {
  const p = join(base, 'playwright', 'lib', 'transform', 'babelBundle.js');
  if (existsSync(p)) { try { babel = createRequire(import.meta.url)(p); break; } catch {} }
}

// What babel calls a definition the map indexes, a call, and the named
// function a call is made from, by the map's own rules: a function or
// class declaration, an arrow or function expression assigned to a name, a
// key or a default parameter, a method; a call by its callee's last name.
function truth(code, file) {
  let ast;
  for (const mod of [file.endsWith('.mjs'), !file.endsWith('.mjs')]) {
    try { ast = babel.babelParse(code, file, mod); break; } catch (e) { ast = null; }
  }
  if (!ast) return null;
  const defs = [], calls = [];
  const nameOf = path => {
    const n = path.node, par = path.parent;
    if (n.type === 'FunctionDeclaration' && n.id) return n.id.name;
    if (n.type === 'ClassDeclaration' && n.id) return n.id.name;
    if (n.type === 'ClassMethod' || n.type === 'ObjectMethod')
      return n.key.type === 'Identifier' ? n.key.name : null;
    if (n.type === 'ClassPrivateMethod') return n.key.id.name;
    if (n.type === 'ArrowFunctionExpression' || n.type === 'FunctionExpression') {
      if (par.type === 'VariableDeclarator' && par.id.type === 'Identifier') return par.id.name;
      if (par.type === 'AssignmentExpression' && par.left.type === 'Identifier') return par.left.name;
      if (par.type === 'AssignmentExpression' && par.left.type === 'MemberExpression' && !par.left.computed)
        return par.left.property.name;
      if (par.type === 'AssignmentPattern' && par.left.type === 'Identifier') return par.left.name;
      if (par.type === 'ObjectProperty' && par.key.type === 'Identifier') return par.key.name;
      if (n.id) return n.id.name;
    }
    return null;
  };
  babel.traverse(ast, {
    enter(path) {
      const n = path.node;
      const name = nameOf(path);
      if (name) defs.push({ name, line: n.loc.start.line, end: n.loc.end.line, kind: n.type });
      if (n.type === 'CallExpression' || n.type === 'NewExpression' || n.type === 'OptionalCallExpression') {
        const c = n.callee;
        let cn = null;
        if (c.type === 'Identifier') cn = c.name;
        else if ((c.type === 'MemberExpression' || c.type === 'OptionalMemberExpression') && !c.computed)
          cn = c.property.type === 'PrivateName' ? c.property.id.name : c.property.name;
        if (!cn) return;
        let caller = '';
        for (let q = path.parentPath; q; q = q.parentPath) {
          const f = q.node.type;
          if (/Function|Method/.test(f)) { const nm = nameOf(q); if (nm) { caller = nm; break; } }
        }
        calls.push({ name: cn, line: c.loc.end.line, caller });
      }
    },
  });
  return { defs, calls };
}

// The map's answer for one file beside babel's: every definition babel
// names is the map's with the same end, every call is recorded, and from
// the same function, but where the map says (anonymous), which is by design.
function compare(entry, t) {
  const bad = [];
  const have = new Map(entry.defs.map(d => [`${d.name}:${d.line}`, d]));
  for (const d of t.defs) {
    const m = have.get(`${d.name}:${d.line}`);
    if (!m) bad.push({ missing: d.name, line: d.line });
    else if (m.end !== d.end) bad.push({ end: d.name, line: d.line, map: m.end, babel: d.end });
  }
  const tk = new Set(t.defs.map(d => `${d.name}:${d.line}`));
  for (const d of entry.defs)
    if (!d.name.startsWith('(') && !['class', 'interface'].includes(d.kind) && !tk.has(`${d.name}:${d.line}`))
      bad.push({ extra: d.name, line: d.line, kind: d.kind });
  const calls = new Map();
  for (const c of entry.calls) {
    const k = `${c.name}:${c.line}`;
    calls.set(k, [...(calls.get(k) || []), c.caller]);
  }
  for (const c of t.calls) {
    const got = calls.get(`${c.name}:${c.line}`);
    if (!got) { bad.push({ call: c.name, line: c.line }); continue; }
    const want = c.caller || '(top level)';
    if (!got.includes(want) && !got.includes('(anonymous)')) bad.push({ caller: c.name, line: c.line, want, map: got });
  }
  return bad;
}

// ---- 1. this tree against babel -------------------------------------------------
const idx = build(REPO);
if (!babel) {
  console.log('SKIP  babel is not in this harness (NODE_PATH has no playwright/lib/transform/babelBundle.js): the JS half did not run');
} else {
  const bad = {};
  let files = 0;
  for (const [file, entry] of Object.entries(idx.files)) {
    if (!/\.(js|mjs)$/.test(file)) continue;
    // (a suite running beside this one can make a file and remove it again)
    let code;
    try { code = readFileSync(join(REPO, file), 'utf8'); } catch { continue; }
    const t = truth(code, file);
    if (!t) { bad[file] = [{ babel: 'could not parse' }]; continue; }
    files++;
    const b = compare(entry, t);
    if (b.length) bad[file] = b;
  }
  ok(Object.keys(bad).length === 0 && files > 50,
     `the map agrees with babel on every definition, end, call and caller in this tree's ${files} scripts${
       Object.keys(bad).length ? ': ' + Object.entries(bad).slice(0, 3).map(([f, b]) => `${f} ${show(b)}`).join(' | ') : ''}`);
  // The page's inline scripts, at their own lines.
  const page = 'scripts/dashboard/index.html';
  const html = readFileSync(join(REPO, page), 'utf8');
  const only = html.replace(/[^\n]/g, ' ').split('');
  for (const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
    const at = m.index + m[0].indexOf(m[1]);
    for (let k = 0; k < m[1].length; k++) only[at + k] = html[at + k];
  }
  const tp = truth(only.join(''), 'page.js');
  const bp = tp ? compare(idx.files[page], tp) : [{ babel: 'could not parse' }];
  ok(bp.length === 0 && tp.defs.length > 20,
     `...and on index.html's inline scripts (${tp ? tp.defs.length : 0} definitions)${bp.length ? ': ' + show(bp) : ''}`);
}

// ---- 2. this tree's python against its own ast ----------------------------------
{
  const py = execFileSync('python3', ['-c', `
import ast, json, sys
idx = json.load(open(sys.argv[1]))
bad = []
for p, f in idx["files"].items():
    if f["lang"] != "py":
        continue
    try:
        t = ast.parse(open(sys.argv[2] + "/" + p, errors="replace").read())
    except SyntaxError:
        continue
    have = {(d["name"], d["line"]): d["end"] for d in f["defs"]}
    calls = {(c["name"], c["line"]) for c in f["calls"]}
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            k = (n.name, n.lineno)
            if have.get(k) != n.end_lineno:
                bad.append([p, n.name, n.lineno, have.get(k), n.end_lineno])
        if isinstance(n, ast.Call):
            fu = n.func
            nm = fu.id if isinstance(fu, ast.Name) else fu.attr if isinstance(fu, ast.Attribute) else None
            if nm and (nm, n.lineno) not in calls:
                bad.append([p, "call", nm, n.lineno])
print(json.dumps(bad[:10] + [len(bad)]))
`, join(REPO, '.bb-map', 'map3.json'), REPO], { encoding: 'utf8' });
  const r = JSON.parse(py);
  ok(r[r.length - 1] === 0, `the map agrees with python's ast on every def, its end and every call in this tree${
    r.length > 1 ? ': ' + show(r.slice(0, -1)) : ''}`);
}

// ---- 3. the languages no parser here reads, answered by hand --------------------
// Each was a way the map went wrong on a real project (B576 to B590). The
// expected lines are the code's own, counted by hand and held here.
const FIX = `${DIR}/codemap-parsers`;
const fixture = {
  'src/solver.ts': `export const add = (a: Vec, b: Vec): Vec => a.map(f);
export class Search {
  private bound(base: Vec, arts: (number | null)[]): [number, number] {
    const m = new Map<number, Set<number>>();
    return [0, 0];
  }
  #drift() { tick(); }
  constructor({ now = Date.now } = {}) {
    this.#drift();
  }
}
function prepare(input: In): { preps: Prep[]; problems: string[] } {
  return go();
}
export interface Plan { slot: number }
`,
  'src/ui.tsx': `export function Card({ s }: { s: S }) {
  return <p class="hint">It isn't set: 3 class-item mods</p>;
}
export function Row({ p }: { p: P }) {
  return <td>{p ? <Name x={1} /> : '-'}</td>;
}
`,
  'app/G.kt': `object G {
    fun reach(s: FloatArray?): Float = 1f
    fun add(outcome: Int, reach: Float = -1f) {
        if (reach >= 0f) { x(reach) }
    }
    fun record(x: Int) {
    }
    private fun <T> List<T>.move(a: Int): List<T> {
        return this
    }
    fun pair(): Pair<Uri, String>? {
        return null
    }
    fun t() {
        add(1, reach = 0.6f)
    }
    private fun Map<String, Any?>.long(key: String): Long? = when (val v = this[key]) {
        else -> null
    }
}
interface Voice {
    fun onText(t: String)
}
`,
  'lib/common.sh': `die() { echo "$*" >&2; exit 1; }
`,
  'tool': `#!/bin/bash
. "$(dirname "$0")/lib/common.sh"
outer() {
    inner() {
        die "inner: run this as root"
    }
    inner
}
trap 'outer' EXIT
`,
  'native/q.c': `static int (*pick(int k))(int) {
    return k ? inc : dec;
}
int old_style(a, b)
int a; int b;
{
    return a + b;
}
`,
  'wp/plugin.php': `<?php
add_action('init', function () {
    boot();
});
add_filter('a', fn() => 'closed');
`,
};
for (const [f, text] of Object.entries(fixture)) {
  mkdirSync(dirname(`${FIX}/${f}`), { recursive: true });
  writeFileSync(`${FIX}/${f}`, text);
}
const fx = build(FIX);
const defsOf = f => (fx.files[f]?.defs || []).filter(d => !d.name.startsWith('('))
  .map(d => `${d.name}:${d.line}-${d.end}`);
const callsOf = f => (fx.files[f]?.calls || []).map(c => `${c.name}@${c.line}<${c.caller}`);
const want = (f, xs, what) => {
  const got = defsOf(f);
  const miss = xs.filter(x => !got.includes(x));
  ok(miss.length === 0, `${what} (${f}: ${miss.length ? 'missing ' + miss.join(' ') + '; has ' + got.join(' ') : xs.length + ' as written'})`);
};
want('src/solver.ts', ['add:1-1', 'Search:2-11', 'bound:3-6', 'drift:7-7', 'constructor:8-10', 'prepare:12-14'],
     'TypeScript: return types after an arrow and a method, a #private method, a destructured constructor, an object return type');
ok(callsOf('src/solver.ts').includes('Map@4<bound') && callsOf('src/solver.ts').includes('go@13<prepare'),
   `...and a generic call new Map<K, V>() is a call from its method (${callsOf('src/solver.ts').join(' ')})`);
want('src/ui.tsx', ['Card:1-3', 'Row:4-6'], 'JSX text with an apostrophe and a self-closing tag ends each component where it ends');
ok(!defsOf('src/ui.tsx').some(d => d.startsWith('item:')), '...and "class-item" in JSX text is no class');
want('app/G.kt', ['reach:2-2', 'add:3-5', 'record:6-7', 'move:8-10', 'pair:11-13', 't:14-16', 'long:17-19', 'onText:22-22'],
     'Kotlin: a fun named like another language\'s keyword, a generic extension fun, one on Map<String, Any?>, a nullable generic return type, an interface fun with no body');
{
  const who = execFileSync('python3', [CODEMAP, '--root', FIX, 'who-calls', 'reach'], { encoding: 'utf8' });
  ok(!/passed by name/.test(who), `...and a parameter or a named argument called reach is not the function reach passed on (${who.trim().split('\n')[0]})`);
}
want('tool', ['outer:3-8', 'inner:4-6'], 'shell: a nested function ends at its own brace');
ok(callsOf('tool').includes('die@5<inner') && callsOf('tool').includes('outer@9<(top level)')
   && !callsOf('tool').some(c => c.startsWith('run@')),
   `...calls what it sources (die, from lib/common.sh), counts a trap's command, and nothing in quoted text (${callsOf('tool').join(' ')})`);
want('native/q.c', ['pick:1-3', 'old_style:4-8'], 'C: a function returning a function pointer and a K&R definition');
{
  const defs = execFileSync('python3', [CODEMAP, '--root', FIX, 'defs', 'wp/plugin.php'], { encoding: 'utf8' }).trim();
  ok(defs === '2-4  function (anonymous) passed to add_action\n5  function (anonymous) passed to add_filter',
     `PHP: a file of closures lists each with what it is handed to (${defs.replace(/\n/g, ' | ')})`);
}

await done();
