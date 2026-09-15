// The dashboard's modules take their dependencies by injection: the server
// calls each one's configure(), which writes names into the module with
// globals().update(...). A name written that way and never declared at
// module level is invisible to every tool: ruff reports it undefined, and
// a reader has to find the server's call to learn what the module needs
// (roadmap R55, step 2: three of bugs.py's were exactly that). This holds
// the line: every injected name is declared where the module's own
// constants are. No browser: it is a read of the source.
import { ok, done } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const out = execFileSync('python3', ['-c', `
import ast, glob, os, sys
gaps = []
for f in sorted(glob.glob(os.path.join(${JSON.stringify(join(HERE, '..'))}, "*.py"))):
    tree = ast.parse(open(f).read())
    declared = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    declared.add(t.id)
                elif isinstance(t, ast.Tuple):     # a, b = {}, 0
                    declared.update(e.id for e in t.elts if isinstance(e, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            declared.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            declared.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            declared.update((a.asname or a.name).split(".")[0] for a in node.names)
    injected = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update" and isinstance(node.func.value, ast.Call)
                and getattr(node.func.value.func, "id", "") == "globals"):
            injected.update(kw.arg for kw in node.keywords if kw.arg)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Call)
                        and getattr(t.value.func, "id", "") == "globals"
                        and isinstance(t.slice, ast.Constant)):
                    injected.add(t.slice.value)
    for name in sorted(injected - declared):
        gaps.append(f"{os.path.basename(f)}: {name}")
print("\\n".join(gaps))
`], { encoding: 'utf8' }).trim();
ok(out === '', `every name a module takes from configure() is declared at its top${out ? ': ' + out.replace(/\n/g, '; ') : ''}`);
await done(null);
