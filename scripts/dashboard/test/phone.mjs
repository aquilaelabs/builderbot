// The Phone tab: a handset on wireless adb, driven from a node, owned by the
// account that connected it, and the questions a session leaves for that
// account. Installing an APK from the Artifacts tab goes through the same
// node, so that half is here too.
//
// The harness's sandbox node runs agent-stub.py with the stubbed adb on its
// PATH, so every adb command the tab sends becomes a job there and answers as
// a phone that is always present. That is not a shortcut — a real adb answers
// from whatever is actually paired to the box the suite runs on, which makes
// the result a fact about the room rather than the code.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { execSync, execFileSync } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const base = URL.replace(/\/$/, '');
const asUser = (u, pw) => ({ Authorization: 'Basic ' + Buffer.from(`${u}:${pw}`).toString('base64'),
                             'Content-Type': 'application/json' });
const owner = asUser('test', 'test');
const api = async (path, body, headers = owner) => {
  const r = await fetch(base + path, body === undefined ? { headers }
    : { method: 'POST', headers, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

// ---- the node that holds the phone ---------------------------------------
const sandbox = (await api('/api/v1/nodes')).body.nodes.find(n => n.name === 'sandbox');
ok(sandbox && sandbox.reported?.toolchains?.adb,
   'the fixture node reports adb in its census, which is what makes it a place for a phone');
// alpha's sessions reach the phone on alpha's node and no other.
await api('/api/prefs', { project: 'alpha', node: sandbox.id });

await page.evaluate(() => openPhoneTab());
await page.waitForSelector('.phonetab .row', { timeout: 20000 });
ok(await page.$eval('.phonetab #phPick', s => [...s.options].some(o => o.textContent.includes('sandbox'))),
   'the tab opens with a node picker naming the node that carries adb');
ok(await page.$('.card[data-card="phone"]') === null && await page.$('#bPhone') !== null,
   'the phone is a tab reached from Tools, not a card in the sidebar');

// ---- what the server refuses ----------------------------------------------
for (const [what, body] of [
  ['an address that is not one', { action: 'connect', node: sandbox.id, ip: 'not-an-ip' }],
  ['a port that is not one', { action: 'connect', node: sandbox.id, ip: '192.168.9.9', port: '99999999' }],
  ['a pairing code that is not six digits', { action: 'pair', node: sandbox.id, ip: '192.168.9.9', port: '5555', code: '12' }],
  ['connecting with no node picked', { action: 'connect', ip: '192.168.9.9', port: '5555' }],
  ['an action nobody offers', { action: 'reboot', node: sandbox.id }],
]){
  const r = await api('/api/phone', body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
page.errors = [];

// ---- connecting, and who then owns it --------------------------------------
// With the port given, so nothing scans: the scan is a job on the node
// probing the phone's network, and the fixture's phone is a stub.
const conn = await api('/api/phone', { action: 'connect', node: sandbox.id, ip: '192.168.9.9', port: '5555' });
ok(conn.status === 200 && conn.body.serial === '192.168.9.9:5555',
   `Connect runs adb on the node and reports the serial (${JSON.stringify(conn.body).slice(0, 80)})`);
const mine = conn.body.nodes.find(n => n.id === sandbox.id);
ok(mine.phone?.model === 'Test Phone' && mine.mine && mine.owner?.name === 'test',
   'the node now holds a phone, and the account that connected it is its owner');
// The connect above went through the API, not the tab, so the tab is asked
// to read again — as it would on the next revision.
await page.evaluate(() => phFetch());
await page.waitForFunction(() => /connected by test/.test(document.querySelector('.phonetab')?.textContent || ''),
                           null, { timeout: 15000 });
ok(await page.$eval('.phonetab', el => /connected by test \(you\)/.test(el.textContent)),
   'the tab shows the phone by model and says whose connection it is');
ok(await page.$('.phonetab #phDisconnect') !== null, '...and offers Disconnect to the owner');

// A second account sees the connection and cannot drive it.
execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'visitor', '--role', 'admin'],
  { input: 'visitorpass1\nvisitorpass1\n', encoding: 'utf8',
    env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
const other = asUser('visitor', 'visitorpass1');
// Given the project, so what is refused below is refused for ownership and
// not for never having taken the project on.
await api('/api/users', { action: 'projects', name: 'visitor', projects: ['alpha'] });
const theirs = (await api('/api/phone?node=' + sandbox.id, undefined, other)).body;
const seen = theirs.nodes.find(n => n.id === sandbox.id);
ok(seen.phone?.model === 'Test Phone' && !seen.mine && !seen.may_drive && seen.owner?.name === 'test',
   'another account sees the phone and who connected it, and may not drive it');
const theirDisc = await api('/api/phone', { action: 'disconnect', node: sandbox.id }, other);
ok(theirDisc.status === 400 && /connected by test/.test(theirDisc.body.error),
   'only the account that connected a phone can disconnect it, and the refusal names them');
const theirConn = await api('/api/phone', { action: 'connect', node: sandbox.id, ip: '192.168.9.9', port: '5555' }, other);
ok(theirConn.status === 400 && /connected by test/.test(theirConn.body.error),
   '...nor connect over it');

// ---- a session asking, and who is asked ------------------------------------
// The point of the whole arrangement: a session does not touch the handset,
// it describes what it wants and waits — for the account that connected the
// phone, on the project's node, and nobody else.
ok((await api('/api/phone', { action: 'ask', why: '', cmd: ['shell', 'ls'], project: 'alpha' })).body.error,
   'an ask with no reason is refused — Allow on an unexplained command is a guess');
const noNode = await api('/api/phone', { action: 'ask', why: 'look around', cmd: ['shell', 'ls'], project: 'beta' });
ok(/has no node/.test(noNode.body.error || ''),
   'a project with no node has no phone to ask for, and is told so');
const asked = await api('/api/phone', { action: 'ask', why: 'read the Firefox version',
                                        cmd: ['shell', 'getprop', 'ro.build.version.release'], project: 'alpha' });
ok(asked.body.id > 0 && asked.body.to === 'test',
   `a session can ask, and is told who was asked (${JSON.stringify(asked.body).slice(0, 80)})`);
ok((await api('/api/phone', undefined, other)).body.asks.length === 0,
   'the other account is not asked — the question goes to the connection\'s owner alone');
await page.evaluate(() => phFetch());
await page.waitForSelector('.phask', { timeout: 15000 });
ok(/read the Firefox version/.test(await page.$eval('.phask', e => e.textContent))
   && /alpha on sandbox/.test(await page.$eval('.phask', e => e.textContent)),
   'the owner\'s tab shows the request with its reason, its project and its node');
ok(/left to answer/.test(await page.$eval('.phask', e => e.textContent)),
   '...and how long is left, since an Allow that has quietly stopped working is worse than one that says it has gone');
// The bell carries the same ask, because a session blocked on an answer
// should not depend on which tab you are looking at. Amber rather than red.
await page.waitForFunction(
  () => { const d = document.querySelector('#bBell .dot');
          return d && !d.hidden && d.classList.contains('ask'); },
  null, { timeout: 15000 });
ok(true, 'an ask lights the bell, in the colour that means somebody is waiting');
await page.click('#bBell');
await page.waitForSelector('#bellPanel .bnote.ask', { timeout: 10000 });
ok(/read the Firefox version/.test(await page.$eval('#bellPanel .bnote.ask', e => e.textContent))
   && /getprop/.test(await page.$eval('#bellPanel .bnote.ask .bcmd', e => e.textContent)),
   '...and the panel carries the reason and the exact command, as the tab does');
await page.evaluate(() => notify('something went wrong', true));
await page.waitForSelector('#bellPanel .bnote.bad', { timeout: 10000 });
await page.click('#bellClear');
await page.waitForFunction(() => !document.querySelector('#bellPanel .bnote.bad'));
ok(await page.$('#bellPanel .bnote.ask') !== null,
   'clearing the log leaves the ask, which is not this button\'s to dismiss');
await page.keyboard.press('Escape');
await page.waitForFunction(() => document.getElementById('bellPanel').hidden);

const theirAllow = await api('/api/phone', { action: 'allow', id: asked.body.id }, other);
ok(theirAllow.status === 400 && /account that connected/.test(theirAllow.body.error),
   'another account cannot answer for it');
await page.click('.phask [data-allow]');
await page.waitForFunction(() => !document.querySelector('.phask'), null, { timeout: 20000 });
await page.waitForFunction(() => document.title === 'BuilderBot', null, { timeout: 15000 });
ok(true, '...and the badge clears when nothing is waiting');
const done1 = await api('/api/phone', { action: 'outcome', id: asked.body.id });
ok(done1.body.state === 'done', 'Allow runs it — on the node, not in the session');
const denied = await api('/api/phone', { action: 'ask', why: 'wipe something',
                                         cmd: ['shell', 'rm', '-rf', '/sdcard/x'], project: 'alpha' });
await page.evaluate(() => phFetch());
await page.click('#bBell');
await page.waitForSelector('#bellPanel .bnote.ask [data-bdeny]', { timeout: 10000 });
await page.click('#bellPanel .bnote.ask [data-bdeny]');
await page.waitForFunction(() => !document.querySelector('.phask'), null, { timeout: 20000 });
ok((await api('/api/phone', { action: 'outcome', id: denied.body.id })).body.state === 'denied',
   'Deny stops it, and the session is told no rather than left hanging');
ok((await api('/api/phone', { action: 'allow', id: denied.body.id })).body.error,
   '...and an answered request cannot be answered again');

// A request is answered only to the project that made it, and a session
// reads the phone from the cache rather than asking a node it is not bound
// to: ids are a small counter, and a probe is a job on somebody's machine.
{
  const mint = (proj) => execFileSync('python3', ['-c', `
import importlib.util, json, os
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
def wj(p, d):
    tmp = str(p) + ".tmp"; open(tmp, "w").write(json.dumps(d, indent=2)); os.replace(tmp, p)
u.configure(state="${DIR}/state", write_json=wj)
print(u.mint_session("${proj}"))`], { encoding: 'utf8' }).trim();
  const beta = { Authorization: 'Bearer ' + mint('beta'), 'Content-Type': 'application/json' };
  const peek = await api('/api/phone', { action: 'outcome', id: asked.body.id }, beta);
  ok(peek.body.error && peek.body.out === undefined,
     "another project's session cannot read the outcome of a request it did not make");
  const before = (await api('/api/v1/jobs')).body.jobs.length;
  const r = await fetch(base + '/api/phone?node=' + encodeURIComponent(sandbox.id) + '&probe=1', { headers: beta });
  ok(r.status === 200 && (await api('/api/v1/jobs')).body.jobs.length === before,
     'a session asking for a probe is answered from the cache, and no job is queued on the node');
}
await page.keyboard.press('Escape');
page.errors = [];   // the refusals above are 400s on purpose

// ---- installing an APK, through the node --------------------------------
// The Artifacts tab's Install fetches the file onto the project's node and
// runs adb there. The interesting half is the failure: a signature clash is
// the one that actually happens, and it has to arrive as a sentence.
mkdirSync(`${DIR}/ws/alpha/dist/android`, { recursive: true });
writeFileSync(`${DIR}/ws/alpha/dist/android/streamlift-1.2.apk`, 'x');
writeFileSync(`${DIR}/ws/alpha/dist/streamlift-1.3-clash.apk`, 'x');
const instState = async () => (await api('/api/artifacts?project=alpha')).body.install || {};
// Polled from here, not through page.waitForFunction with an async predicate:
// that hands the page a Promise, which is truthy at once, and the wait is no
// wait at all — the install is a job on the node now, and takes a moment.
const instUntil = async (state) => {
  for (let i = 0; i < 100; i++){
    const st = await instState();
    if (st.state === state) return st;
    await new Promise(r => setTimeout(r, 250));
  }
  return await instState();
};
const inst = await api('/api/artifacts', { action: 'install', project: 'alpha', path: 'dist/android/streamlift-1.2.apk' });
ok(inst.status === 200 && !inst.body.error, `Install on a project whose node holds a phone starts (${JSON.stringify(inst.body).slice(0, 60)})`);
const first = await instUntil('done');
ok(first.state === 'done' && first.error === '', `Install runs on the node and reports no error (${JSON.stringify(first)})`);
await api('/api/artifacts', { action: 'install', project: 'alpha', path: 'dist/streamlift-1.3-clash.apk' });
const clash = await instUntil('failed');
ok(/signed with a different key/.test(clash.error),
   `a signature clash is explained, not passed through as INSTALL_FAILED_UPDATE_INCOMPATIBLE (${JSON.stringify(clash)})`);

// ---- pushing an extension, through the node ------------------------------
// web-ext on the node that holds the phone, as a job that stays running: the
// stub prints the line the real one prints once the add-on is on the phone,
// then sits there like the real one does. The .xpi is put where the agent
// would have fetched it — the fixture agent fetches nothing.
// A real zip with a manifest, since the node unpacks it before web-ext runs.
for (const f of [`${DIR}/ws/alpha/dist/companion-0.2.0.xpi`, `${DIR}/sandboxdata/companion-0.2.0.xpi`])
  execFileSync('python3', ['-c', 'import sys,zipfile; z=zipfile.ZipFile(sys.argv[1],"w"); z.writestr("manifest.json","{}"); z.close()', f]);
const summary = async (h = owner) => (await api('/api/artifacts?project=alpha', undefined, h)).body;
const mineSum = await summary();
ok(mineSum.mine && mineSum.webext && mineSum.apks.includes('org.mozilla.firefox_beta'),
   `the Artifacts view is told the phone is this account's, the node has web-ext, and which Firefox is there (${JSON.stringify([mineSum.mine, mineSum.webext, mineSum.apks])})`);
const theirSum = await summary(other);
ok(theirSum.phone && !theirSum.mine && theirSum.owner?.name === 'test',
   '...and another account is told the phone is there and not theirs');
const theirPush = await api('/api/artifacts', { action: 'push', project: 'alpha', path: 'dist/companion-0.2.0.xpi', apk: 'org.mozilla.firefox_beta' }, other);
ok(theirPush.status === 400 && /connected by test/.test(theirPush.body.error),
   'a push from another account is refused, naming who connected the phone');
const theirInst = await api('/api/artifacts', { action: 'install', project: 'alpha', path: 'dist/android/streamlift-1.2.apk' }, other);
ok(theirInst.status === 400 && /connected by test/.test(theirInst.body.error),
   '...and so is an install');
const pushed = await api('/api/artifacts', { action: 'push', project: 'alpha', path: 'dist/companion-0.2.0.xpi', apk: 'org.mozilla.firefox_beta' });
ok(pushed.status === 200 && pushed.body.job,
   `the owner's push starts as a job on the node (${JSON.stringify(pushed.body).slice(0, 80)})`);
let pushSt = {};
for (let i = 0; i < 100 && pushSt.state !== 'running'; i++){
  pushSt = (await summary()).push || {};
  await new Promise(r => setTimeout(r, 250));
}
ok(pushSt.running && pushSt.state === 'running',
   `...and goes live once web-ext says the add-on is on the phone (${JSON.stringify(pushSt).slice(0, 100)})`);
const again = await api('/api/artifacts', { action: 'push', project: 'alpha', path: 'dist/companion-0.2.0.xpi', apk: 'org.mozilla.firefox_beta' });
ok(again.status === 400 && /already pushing/.test(again.body.error),
   'a second push cannot start on top of the first');
const theirStop = await api('/api/artifacts', { action: 'stop', project: 'alpha' }, other);
ok(theirStop.status === 400 && /owner/.test(theirStop.body.error),
   'another account cannot stop it');
await api('/api/artifacts', { action: 'stop', project: 'alpha' });
for (let i = 0; i < 100 && pushSt.running; i++){
  pushSt = (await summary()).push || {};
  await new Promise(r => setTimeout(r, 250));
}
ok(!pushSt.running, 'the owner stops it, and the job ends');

// ---- browsing from the phone itself ----------------------------------------
const asDesktop = (await api('/api/phone')).body;
ok(asDesktop.you === undefined,
   'from a desktop the tab is not told an address — the browser is not the phone');
const lan = execSync("hostname -I").toString().trim().split(/\s+/)
  .find(a => /^\d+\.\d+\.\d+\.\d+$/.test(a) && !a.startsWith('127.'));
const asPhone = !lan ? { you: 'no LAN address on this box — nothing to ask with' }
  : await (await fetch(URL.replace('127.0.0.1', lan) + 'api/phone', {
  headers: { 'User-Agent': 'Mozilla/5.0 (Android 17; Mobile; rv:145.0) Firefox/145.0',
             Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') }
})).json();
ok(typeof asPhone.you === 'string' && (!lan || /^\d+\.\d+\.\d+\.\d+$/.test(asPhone.you)),
   `from an Android browser it offers that browser's own address (${asPhone.you})`);

// ---- the owner ends it ------------------------------------------------------
await page.click('.phonetab #phDisconnect');
await page.waitForFunction(() => !document.querySelector('.phonetab #phDisconnect'), null, { timeout: 20000 });
ok(!(await api('/api/phone?node=' + sandbox.id)).body.nodes.find(n => n.id === sandbox.id).owner,
   'the owner disconnects, and the connection has no owner afterwards');
const noPhone = await api('/api/phone', { action: 'ask', why: 'look around', cmd: ['shell', 'ls'], project: 'alpha' });
ok(/no phone is connected on sandbox/.test(noPhone.body.error || ''),
   'with nothing connected, a session is told which node to connect one on');
page.errors = [];

// ---- what the bell says, and how loudly -----------------------------------
const dots = await page.evaluate(() => {
  const seen = {};
  const dot = () => document.querySelector('#bBell .dot').className;
  const bell = document.getElementById('bBell');
  const saved = ph.asks, savedAtt = state.attention;
  ph.asks = []; state.attention = [];    // an ask, or a node alert, outranks every level by design
  const reset = () => { notes = []; notesSeen = 0; };
  reset(); notify('a build finished');                    seen.info = dot();
  reset(); notify('the emulator is low on disk', 'warn'); seen.warn = dot();
  reset(); notify('compose up failed', true);             seen.bad = dot();
  reset(); notify('compose up failed', true); notify('saved');
  seen.worst = dot();
  reset(); notesSeen = notes.length; drawBell();
  seen.none = document.querySelector('#bBell .dot').hidden;
  seen.quiet = bell.classList.contains('waiting');
  ph.asks = [{id: 1, why: 'read a property', cmd: ['shell', 'getprop'], left: 300, node_name: 'sandbox'}];
  drawBell();
  seen.asking = dot();
  seen.loud = bell.classList.contains('waiting');
  ph.asks = saved; state.attention = savedAtt; reset(); drawBell();
  return seen;
});
ok(dots.info === 'dot info' && dots.warn === 'dot warn' && dots.bad === 'dot bad',
   'the dot is blue for something worth knowing, amber for a warning, red for a failure');
ok(dots.worst === 'dot bad',
   '...the worst of what is unread, so a later "saved" cannot bury a failure');
ok(dots.none === true && dots.quiet === false,
   '...and nothing at all when there is nothing unread');
ok(dots.asking === 'dot ask' && dots.loud === true,
   'a question waiting on an answer lights the whole button, not just the dot');

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
// The admin account made above is not the fixture's; users.json outlives
// this file, so it goes with it.
await api('/api/users', { action: 'remove', name: 'visitor' });
await done(browser);
