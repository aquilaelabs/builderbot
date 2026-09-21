// A real node, on the other end of a real agent (roadmap R54 step 4).
//
// Everything the harness proves about nodes it proves against a stub: a fake
// agent, a stub docker, a dpkg that says everything is missing. That is the
// right way to test the controller's half and it cannot tell you whether an
// agent on another machine takes a job, runs it as the account it should, and
// reports a store that is really there. This does, against a controller and a
// node named in the environment:
//
//   BB_LAB_CONTROLLER  the dashboard to ask, e.g. http://192.168.1.16:7680
//   BB_LAB_TOKEN       basic-auth credentials for an administrator there,
//                      "user:password" (the lab's own, never production's)
//   BB_LAB_NODE        the node to run on, by name or id. A job runs there,
//                      so name one you are willing to have that happen to.
//
// Skipped in one line without them, like every lab suite: absent is not a
// failure, and none of this runs in CI.
//
// What it does to the node is deliberately the smallest real thing: a
// toolchain CHECK, which asks each upstream what it has and writes nothing to
// the store. Nothing here installs, removes or starts anything.
import { ok, done } from './lib.mjs';

const CTL = (process.env.BB_LAB_CONTROLLER || '').replace(/\/$/, '');
const CRED = process.env.BB_LAB_TOKEN || '';
const WANT = process.env.BB_LAB_NODE || '';
if (!CTL || !CRED || !WANT){
  console.log('SKIP  lab-node: BB_LAB_CONTROLLER, BB_LAB_TOKEN and BB_LAB_NODE are not all set');
  process.exit(0);
}

const auth = 'Basic ' + Buffer.from(CRED).toString('base64');
const api = async (path, body) => {
  const r = await fetch(CTL + path, body === undefined
    ? { headers: { Authorization: auth } }
    : { method: 'POST', headers: { Authorization: auth, 'Content-Type': 'application/json' },
        body: JSON.stringify(body) });
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { j = { raw: text.slice(0, 200) }; }
  return { status: r.status, ...j };
};
const wait = async (fn, ms = 120000, every = 3000) => {
  const until = Date.now() + ms;
  for (;;) {
    const got = await fn();
    if (got) return got;
    if (Date.now() > until) return null;
    await new Promise(r => setTimeout(r, every));
  }
};

// ---- the node is there, and its agent can be spoken to ---------------------
const list = await api('/api/v1/nodes');
const node = (list.nodes || []).find(n => n.id === WANT || n.name === WANT);
ok(node && node.kind === 'agent',
   `the node named in BB_LAB_NODE is enrolled and runs an agent (${
     node ? `${node.name}: ${node.kind}` : `no node called ${WANT}`})`);
if (!node){ await done(null); process.exit(0); }

ok(node.state === 'online' && node.live,
   `...and it is dialing in now, which is what makes a job on it mean anything (${
     node.state}${node.live ? ', live' : ', quiet'})`);

// An agent that is behind takes nothing but its own update, so every job
// below would be testing that refusal rather than the node. The rule is the
// controller's own: the digest it ships against the digest the node reports,
// which is why this compares those and not the version strings.
const ours = (list.agent || {}).digest || '';
const theirs = (node.agent || {}).digest || '';
ok(ours && theirs && ours === theirs,
   `...and it runs the agent this controller ships, so a job sent to it means something (node ${
     (node.agent || {}).version || '?'}, controller ${(list.agent || {}).version || '?'}${
     ours && theirs && ours !== theirs ? ': press Update agent on its row' : ''})`);

// ---- what it says about itself ---------------------------------------------
const rep = node.reported || {};
ok((rep.cpu || 0) > 0 && (rep.mem_mb || 0) > 0,
   `the census carries real numbers from that machine (${rep.cpu} cpu, ${rep.mem_mb}MB)`);
const store = (rep.stores || {}).toolchains || {};
ok(store.path && typeof store.free_mb === 'number',
   `...and a toolchain store that is really there, with headroom (${
     store.path || 'none'}${store.scope ? '/' + store.scope : ''}, ${store.free_mb}MB free)`);
ok(typeof rep.system === 'string' && typeof rep.arch === 'string',
   `...and the platform, which decides what may be installed there (${rep.system}/${rep.arch})`);

// ---- a job, run by that agent, on that machine ------------------------------
// A check: it asks each upstream what it has and writes nothing to the store,
// so this suite can run on a node somebody is using.
const queued = await api('/api/toolchains', { action: 'check', node: node.id, names: ['zig'] });
ok(queued.ok && /^j_/.test(queued.job || ''),
   `a toolchain check is queued for that node (${queued.job || queued.error})`);
if (queued.job){
  const fin = await wait(async () => {
    const j = await api(`/api/v1/jobs?id=${queued.job}`);
    return ['succeeded', 'failed', 'canceled'].includes(j.state) ? j : null;
  });
  ok(fin && fin.state === 'succeeded',
     `...and the agent there ran it (${fin ? fin.state : 'never finished'})`);
  ok(fin && /bb toolchains check/.test(fin.log || ''),
     '...through the bundle this controller ships, not a copy on the machine');
  const view = await api(`/api/toolchains?node=${node.id}`);
  const row = (view.items || []).find(i => i.name === 'zig');
  ok(view.checked > 0 && row && row.state,
     `...and the answer reached the row, from that machine's own reading (${
       row ? `${row.name}: ${row.state} ${row.latest || ''}` : 'no zig row'})`);
}

// ---- what a second node would add, said rather than pretended --------------
const others = (list.nodes || []).filter(n => n.kind === 'agent' && n.id !== node.id
                                              && n.state !== 'retired');
if (!others.length){
  console.log('NOTE  lab-node: one agent node here, so the shared-store half of R54 step 4 '
              + 'is not covered: it needs two nodes mounting one store.');
} else {
  // A second node with the SAME store is the arrangement R54 step 4 wants
  // covered, so say which of the two this controller has rather than
  // passing an assertion that cannot fail.
  const mine = ((node.reported || {}).stores || {}).toolchains || {};
  const together = others.filter(o => {
    const s = ((o.reported || {}).stores || {}).toolchains || {};
    return s.id && mine.id && s.id === mine.id;
  });
  if (together.length){
    ok(together.every(o => o.state === 'online'),
       `${together.map(o => o.name).join(', ')} mounts the same toolchain store as ${
         node.name} (store ${mine.id}), which is the arrangement the scope directories are for`);
  } else {
    console.log(`NOTE  lab-node: ${others.map(o => o.name).join(', ')} is enrolled but has a `
                + 'toolchain store of its own, so a shared store is still uncovered.');
  }
}

await done(null);
