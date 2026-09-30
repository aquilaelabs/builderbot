// bb capture (R95). reel: the frames of a recording that changed, stamped and tiled,
// with a JSON of when. Driven on a synthetic video ffmpeg draws with two
// hard changes, so the answer is known: three frames, at 0, 2.0 and 3.5s.
// ffmpeg is a toolchain recipe rather than a given, so a node without it
// says so and this skips rather than failing for a tool it never had.
import { execFileSync, spawnSync, spawn } from 'node:child_process';
import { existsSync, readFileSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { ok, done, DIR } from './lib.mjs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const S = `${DIR}/reel`;
mkdirSync(S, { recursive: true });
// dist/ and the scratch apart (R96): the sheet and frames.json land under
// dist/reel/NAME, the recording and the frames under the scratch, and the
// record names who asked.
const env = { ...process.env, BB_CAPTURE_OUT: `${S}/dist/reel`, BB_CAPTURE_SCRATCH: `${S}/scratch`, BB_ACCOUNT_NAME: 'tester' };
const reel = (...a) => spawnSync('python3', [`${REPO}/scripts/lib/reel.py`, ...a], { encoding: 'utf8', env });
const cap = (...a) => spawnSync('python3', [`${REPO}/scripts/lib/capture.py`, ...a], { encoding: 'utf8', env });

const ff = spawnSync('ffmpeg', ['-version'], { encoding: 'utf8' });
if (ff.status !== 0){
  ok(true, 'skipped: no ffmpeg on this node, which bb capture reel says in its own words');
} else {
  execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
    '-i', 'color=c=navy:size=640x400:rate=10:duration=5',
    '-vf', "drawbox=x=100:y=100:w=300:h=150:color=orange:t=fill:enable='gte(t,2)',drawbox=x=420:y=40:w=150:h=300:color=white:t=fill:enable='gte(t,3.5)'",
    `${S}/cut.mp4`]);
  // A change the size of a typed letter on a phone screen (Shebang-DevBoard,
  // 30 Sep): a 20x40 block on 1080x2400 scores about 0.0003, dropped at a
  // page's threshold, which then says so and how to look closer; kept at
  // the emulator's.
  execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
    '-i', 'color=c=white:size=1080x2400:rate=10:duration=4',
    '-vf', "drawbox=x=130:y=1430:w=26:h=44:color=black:t=fill:enable='gte(t,1.5)',drawbox=x=160:y=1430:w=26:h=44:color=black:t=fill:enable='gte(t,2.5)'",
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', `${S}/letters.mp4`]);
  const coarse = reel('--video', `${S}/letters.mp4`, '--name', 'letters');
  const fine = reel('--video', `${S}/letters.mp4`, '--name', 'letters2', '--threshold', '0.0002');
  const kept = n => (JSON.parse(readFileSync(`${S}/dist/reel/${n}/frames.json`, 'utf8')).frames || []).map(f => f.t);
  ok(kept('letters').length === 1 && /nothing moved past a scene score of 0.02/.test(coarse.stderr) && /--threshold lower/.test(coarse.stderr),
     `a letter-sized change is below a page's threshold, and the reel says so and how to see it (${coarse.stderr.trim().split('\n').pop().slice(0, 90)})`);
  ok(fine.status === 0 && kept('letters2').length === 3 && Math.abs(kept('letters2')[1] - 1.5) < 0.2 && Math.abs(kept('letters2')[2] - 2.5) < 0.2,
     `...and at the emulator's threshold each letter is a frame at its time (${JSON.stringify(kept('letters2'))})`);
  ok(/THRESHOLD = \{"emu": 0\.0002\}/.test(readFileSync(`${REPO}/scripts/lib/reel.py`, 'utf8')),
     '...which is the default for a reel of the emulator');
  cap('prune', `${S}/dist`, 'letters', 'letters2');
  const r = reel('--video', `${S}/cut.mp4`, '--name', 'cut');
  const log = existsSync(`${S}/dist/reel/cut/frames.json`) ? JSON.parse(readFileSync(`${S}/dist/reel/cut/frames.json`, 'utf8')) : null;
  const ts = (log?.frames || []).map(f => f.t);
  ok(r.status === 0 && ts.length === 3 && ts[0] === 0 && Math.abs(ts[1] - 2) < 0.2 && Math.abs(ts[2] - 3.5) < 0.2
     && log.frames[1].change > 0.05 && log.frames[2].change > 0.05 && log.frames[0].change === 0,
     `a video with two changes reels to three frames at their times, with how much moved (${JSON.stringify(ts)}; ${
        (r.stderr || '').trim().split('\n').pop()?.slice(0, 80)})`);
  ok(existsSync(`${S}/dist/reel/cut/sheet.png`) && readFileSync(`${S}/dist/reel/cut/sheet.png`).length > 1000
     && /3 frames changed over 3.5s/.test(r.stderr || ''),
     '...tiled into one sheet, and the verb says how many and over how long');
  ok(/^\s+1\s+2\.0s\s+change/m.test(r.stdout || ''), '...and lists each frame with its time on the terminal');
  const inDist = readdirSync(`${S}/dist/reel/cut`).sort();
  ok(inDist.join(',') === 'frames.json,sheet.png' && existsSync(`${S}/scratch/cut/frames/0001.png`)
     && log.work === `${S}/scratch/cut` && log.frames[0].file === `${S}/scratch/cut/frames/0001.png`
     && /frames are under .*scratch\/cut/.test(r.stderr || ''),
     `dist/ keeps the sheet and the record; the frames are under the scratch, where frames.json and the verb say (${inDist.join(', ')})`);
  ok(log.by === 'tester' && Math.abs(log.at - Date.now() / 1000) < 120,
     `...and the record says who asked and when (${log.by}, ${log.at})`);
  // ls and prune: the one rule the Artifacts tab's sweep applies, from a
  // node. A shot ten days old with its record beside it goes by --days,
  // the reel by name, and a name that is not there is refused naming ls.
  mkdirSync(`${S}/dist/emu`, { recursive: true });
  writeFileSync(`${S}/dist/emu/shot-old.png`, Buffer.from([1, 2, 3]));
  writeFileSync(`${S}/dist/emu/.shot-old.png.json`, JSON.stringify({ by: 'claude', at: Math.floor(Date.now() / 1000) - 10 * 86400 }));
  const ls = cap('ls', `${S}/dist`);
  ok(ls.status === 0 && /reel\s+cut\s+.*ago\s+tester\s+3 frames/.test(ls.stdout) && /shot\s+shot-old\.png\s+10d ago\s+claude/.test(ls.stdout),
     `ls names each capture with whose it is and how old (${ls.stdout.trim().replace(/\s+/g, ' ')})`);
  const byAge = cap('prune', `${S}/dist`, '--days', '7');
  ok(byAge.status === 0 && /1 capture removed/.test(byAge.stderr) && !existsSync(`${S}/dist/emu/shot-old.png`)
     && !existsSync(`${S}/dist/emu/.shot-old.png.json`) && existsSync(`${S}/dist/reel/cut/sheet.png`),
     'prune --days 7 removes the ten-day-old shot and its record, and keeps the reel made just now');
  const none = cap('prune', `${S}/dist`);
  ok(none.status !== 0 && /prune NAME\.\.\. removes those; --days N/.test(none.stderr), 'prune with nothing to go by says what it takes');
  const missing = cap('prune', `${S}/dist`, 'nope');
  ok(missing.status !== 0 && /no such capture: nope; bb capture ls names them/.test(missing.stderr), 'a name that is not there is refused, naming ls');
  const work = JSON.parse(readFileSync(`${S}/dist/reel/cut/frames.json`, 'utf8')).work;
  const byName = cap('prune', `${S}/dist`, 'cut');
  ok(work && !existsSync(work), `pruning a reel takes its working files on this machine with it (report 42: ${work})`);
  ok(byName.status === 0 && !existsSync(`${S}/dist/reel/cut`) && /no captures/.test(cap('ls', `${S}/dist`).stderr),
     'prune NAME lets a capture go now whatever its age');
}
// --emu PKG launches the package only when it is not already on the screen
// (B387): a launch restarts its launcher activity, and the keyboard, dialog
// or deep screen a session had just driven into place was gone from the
// shot. adb is stood in for by a script that answers get-state, the window
// dump from a file, and screencap with one fixed picture, and logs a launch.
{
  const A = `${S}/adb`; mkdirSync(A, { recursive: true });
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kAAAAABJRU5ErkJggg==', 'base64');
  writeFileSync(`${A}/frame.png`, png);
  writeFileSync(`${A}/adb`, `#!/bin/sh
case "$1 $2 $3" in
  "get-state  ") echo device ;;
  "shell dumpsys window") cat "${A}/windows.txt" ;;
  "shell monkey "*) echo "monkey $4 $5" >> "${A}/log" ;;
  "exec-out screencap -p") cat "${A}/frame.png" ;;
esac
exit 0
`, { mode: 0o755 });
  const shot = (name, windows) => {
    writeFileSync(`${A}/windows.txt`, windows);
    writeFileSync(`${A}/log`, '');
    const r = spawnSync('python3', [`${REPO}/scripts/lib/capture.py`, 'shot', '--emu', 'dev.x', '--now', `${A}/${name}.png`],
                        { encoding: 'utf8', env: { ...env, BB_CAPTURE_ADB: `${A}/adb` } });
    return { r, launched: readFileSync(`${A}/log`, 'utf8').trim() };
  };
  const front = shot('front', '  mCurrentFocus=Window{1a2b u0 dev.x/dev.x.Main}\n');
  ok(front.r.status === 0 && front.launched === '' && existsSync(`${A}/front.png`),
     `a package whose activity has the focus is not launched again (${front.launched || 'no launch'}; ${(front.r.stderr || '').trim().slice(0, 60)})`);
  const ime = shot('ime', '  Window #7 Window{9c u0 InputMethod}\n    mOwnerUid=10123 showForAllUsers=false package=dev.x appop=NONE\n    isVisible=true\n  Window #8 Window{2d u0 com.other/.Main}\n  mCurrentFocus=Window{2d u0 com.other/com.other.Main}\n');
  ok(ime.r.status === 0 && ime.launched === '',
     `...nor one whose keyboard is up over another app's window (${ime.launched || 'no launch'})`);
  const away = shot('away', '  Window #8 Window{2d u0 com.other/.Main}\n  mCurrentFocus=Window{2d u0 com.other/com.other.Main}\n');
  ok(away.r.status === 0 && /^monkey dev\.x/.test(away.launched),
     `...and one that is not on the screen is launched first (${away.launched})`);
}

// A timed touch (R101): touch.py finds the panel and the screen through adb
// and sends the whole gesture as one shell of sendevent lines with sleeps,
// in the panel's own range, turned with the screen. The same stand-in adb,
// answering getevent -p, wm size and dumpsys input from files, and logging
// the shell it is handed.
{
  const A = `${S}/adb2`; mkdirSync(A, { recursive: true });
  writeFileSync(`${A}/adb`, `#!/bin/sh
case "$1 $2 $3" in
  "shell getevent -p") printf 'add device 1: /dev/input/event3\n  name:     "qwerty2"\n  events:\n    KEY (0001): 0001\nadd device 2: /dev/input/event2\n  name:     "virtio_input_multi_touch_1"\n  events:\n    ABS (0003): 002f  : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0\n                0035  : value 0, min 0, max 32767, fuzz 0, flat 0, resolution 0\n                0036  : value 0, min 0, max 32767, fuzz 0, flat 0, resolution 0\n' ;;
  "shell wm size") echo "Physical size: 1080x2400" ;;
  "shell dumpsys input") cat "${A}/rotation.txt" ;;
  "shell "*) printf '%s\n' "$2" >> "${A}/log" ;;
esac
exit 0
`, { mode: 0o755 });
  const touch = (...a) => {
    writeFileSync(`${A}/log`, '');
    const r = spawnSync('python3', [`${REPO}/scripts/lib/touch.py`, ...a],
                        { encoding: 'utf8', env: { ...env, BB_CAPTURE_ADB: `${A}/adb` } });
    return { r, sent: readFileSync(`${A}/log`, 'utf8').trim().split(';') };
  };
  writeFileSync(`${A}/rotation.txt`, '  SurfaceOrientation: 0\n');
  const tap = touch('tap', '540', '1200');
  ok(tap.r.status === 0 && tap.sent[0] === 'sendevent /dev/input/event2 3 47 0'
     && tap.sent.includes('sendevent /dev/input/event2 3 53 16398') && tap.sent.includes('sendevent /dev/input/event2 3 54 16390')
     && tap.sent.at(-2) === 'sendevent /dev/input/event2 3 57 -1' && !tap.sent.some(l => l.startsWith('sleep'))
     && /^tap 540,1200: 11 events on \/dev\/input\/event2, about 0 ms$/.test(tap.r.stdout.trim()),
     `a tap finds the panel, scales the screen pixel into its range, and lifts (${tap.r.stdout.trim()} ${(tap.r.stderr || '').trim().slice(0, 80)})`);
  const hold = touch('hold', '100', '100', '--ms', '700');
  ok(hold.r.status === 0 && hold.sent.includes('sleep 0.7') && hold.sent.indexOf('sleep 0.7') < hold.sent.indexOf('sendevent /dev/input/event2 3 57 -1'),
     'a hold keeps the finger down for its time before lifting');
  const glide = touch('glide', '100', '1000', '600', '1000', '--pre', '150', '--hold', '300');
  const moves = glide.sent.filter(l => l === 'sleep 0.012').length;
  ok(glide.r.status === 0 && moves === 20 && glide.sent[8] === 'sleep 0.15' && glide.sent.at(-4) === 'sleep 0.3'
     && /about 690 ms/.test(glide.r.stdout),
     `a glide moves in 25px steps 12 ms apart, holding first and last where asked (${moves} moves; ${glide.r.stdout.trim()})`);
  writeFileSync(`${A}/rotation.txt`, '  SurfaceOrientation: 1\n');
  const turned = touch('tap', '2399', '0');
  ok(turned.r.status === 0 && turned.sent.includes('sendevent /dev/input/event2 3 53 32767') && turned.sent.includes('sendevent /dev/input/event2 3 54 32767')
     && /rotation 1/.test(turned.r.stdout),
     `a landscape tap is turned into the panel's own frame (${turned.r.stdout.trim()})`);
  const bad = touch('glide', '1', '2');
  ok(bad.r.status !== 0 && /a glide needs at least two points/.test(bad.r.stderr), 'a glide of one point is refused in words');
  const noms = touch('hold', '1', '2');
  ok(noms.r.status !== 0 && /hold takes --ms N/.test(noms.r.stderr), '...and a hold without its time');
}

// The sources refuse in their own words when the node lacks what they need.
// An emulator another session holds (30 Sep): the AVD is the account's,
// the emulator in that session's own view, so adb here lists nothing. The
// emulator's lock on the AVD says it is running; status, start and stop
// name it rather than saying none is running or waiting for one that
// refuses to run twice.
{
  const home = `${S}/avdhome`;
  mkdirSync(`${home}/builderbot-36.avd`, { recursive: true });
  mkdirSync(`${home}/running`, { recursive: true });
  writeFileSync(`${home}/builderbot-36.ini`, `path=${home}/builderbot-36.avd\n`);
  writeFileSync(`${home}/builderbot-36.avd/config.ini`, 'image.sysdir.1=x\n');
  writeFileSync(`${home}/builderbot-36.avd/multiinstance.lock`, '');
  writeFileSync(`${home}/running/pid_4242.ini`, 'avd.name=builderbot-36\nport.adb=5555\n');
  const bin = `${S}/emubin`;
  mkdirSync(bin, { recursive: true });
  writeFileSync(`${bin}/adb`, '#!/bin/sh\n[ "$1" = devices ] && echo "List of devices attached"; exit 0\n', { mode: 0o755 });
  writeFileSync(`${bin}/emulator`, '#!/bin/sh\necho "emulator ran" >&2; exit 1\n', { mode: 0o755 });
  const emu = (...a) => spawnSync('bash', [`${REPO}/scripts/bb`, 'emu', ...a], { encoding: 'utf8',
    env: { ...process.env, ANDROID_AVD_HOME: home, ANDROID_AVD_NAME: 'builderbot-36', PATH: `${bin}:${process.env.PATH}`,
           BUILDERBOT_ROLE: 'node', HOME: `${S}/emuhome` } });
  const holder = spawn('flock', [`${home}/builderbot-36.avd/multiinstance.lock`, 'sleep', '600'], { detached: true, stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 400));
  const t0 = Date.now();
  const st = emu('status'), start = emu('start'), stop = emu('stop');
  // Its whole group: flock's sleep holds the lock too.
  try { process.kill(-holder.pid, 'SIGTERM'); } catch {}
  console.log(`[emu held] three calls took ${Date.now() - t0} ms`);
  ok(/builderbot-36 is running in another of your sessions on this node/.test(st.stdout) && !/no emulator is running/.test(st.stdout),
     `bb emu status names an emulator another session holds (${st.stdout.trim().split('\n').pop().slice(0, 80)})`);
  ok(start.status !== 0 && /running in another of your sessions/.test(start.stderr) && !/emulator ran/.test(start.stderr),
     `...bb emu start refuses at once, starting nothing (${start.stderr.trim().split('\n').pop().slice(0, 80)})`);
  ok(/running in another of your sessions/.test(stop.stderr), '...and bb emu stop says whose it is to stop');
  await new Promise(r => setTimeout(r, 200));
  ok(/no emulator is running/.test(emu('status').stdout), '...and with the lock let go, none is running');
}
const noSrc = reel('--name', 'x');
ok(noSrc.status !== 0 && /one source: --video FILE, --url URL, --emu \[PKG\] or --display :N/.test(noSrc.stderr || ''),
   `no source is refused naming the four (${(noSrc.stderr || '').trim().slice(0, 70)})`);
const noDisp = reel('--display', ':77', '--name', 'x');
ok(noDisp.status !== 0 && /no X display :77 on this node.*provisioner adds Xvfb and xdotool/.test(noDisp.stderr || ''),
   `a display the node does not have is refused, naming what the provisioner adds (${(noDisp.stderr || '').trim().slice(0, 80)})`);
const noVid = reel('--video', `${S}/none.mp4`);
ok(noVid.status !== 0 && /no such video/.test(noVid.stderr || ''), 'a video that is not there is refused');
// bb capture shot at rest: shots a quarter second apart until two match, so a page
// whose element lands late is pictured after it does. A page of this
// suite's own, served here, draws its heading at 700 ms: two settled shots
// of it carry the heading and are the same bytes, since nothing moves after
// that, and an immediate shot of a page whose heading comes much later
// carries none. The heading lands inside the second bb capture shot waits
// for; a page that changes later than that is one it cannot know about,
// and --wait is for it.
{
  const { spawn } = await import('node:child_process');
  const web = `${S}/web`; mkdirSync(web, { recursive: true });
  // Two pages (B392). The settled shots take the one whose heading lands
  // at 700 ms, inside the second a settle waits. The --now shot takes one
  // whose heading lands at 20 s: shooting the 700 ms page with --now had to
  // beat its timer, and a headless shot on a box at a load near ten did not.
  const late = ms => '<!doctype html><body style="margin:0;background:#fff">'
    + `<script>setTimeout(() => { document.body.innerHTML = "<h1 style='font:48px sans-serif'>late</h1>"; }, ${ms})</script></body>`;
  writeFileSync(`${web}/index.html`, late(700));
  writeFileSync(`${web}/slow.html`, late(20000));
  const port = 30000 + Math.floor(Math.random() * 20000);
  const srv = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1'], { cwd: web, stdio: 'ignore' });
  // Until it answers rather than a fixed 1.2 s, which a loaded box can miss.
  for (let i = 0; i < 150; i++){
    try { if ((await fetch(`http://127.0.0.1:${port}/`)).ok) break; } catch {}
    await new Promise(r => setTimeout(r, 100));
  }
  const shot = (page, file, ...flags) => spawnSync('bash', [`${REPO}/scripts/bb`, 'capture', 'shot', `http://127.0.0.1:${port}/${page}`, file, ...flags],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_PORT: '1' } });
  const now = shot('slow.html', `${S}/now.png`, '--now'), one = shot('', `${S}/one.png`, '--settle'), two = shot('', `${S}/two.png`, '--settle');
  srv.kill();
  const bytes = f => existsSync(f) ? readFileSync(f) : Buffer.alloc(0);
  ok(now.status === 0 && one.status === 0 && two.status === 0 && bytes(`${S}/one.png`).length > 0
     && !bytes(`${S}/now.png`).equals(bytes(`${S}/one.png`)) && bytes(`${S}/one.png`).equals(bytes(`${S}/two.png`)),
     `bb capture shot --settle pictures a page after its late element lands, and --now pictures it before (${
        [now, one, two].map(r => r.status).join('/')}; ${(one.stderr || '').trim().slice(0, 60)})`);
}
await done();
