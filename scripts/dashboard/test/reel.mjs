// bb reel (R95): the frames of a recording that changed, stamped and tiled,
// with a JSON of when. Driven on a synthetic video ffmpeg draws with two
// hard changes, so the answer is known: three frames, at 0, 2.0 and 3.5s.
// ffmpeg is a toolchain recipe rather than a given, so a node without it
// says so and this skips rather than failing for a tool it never had.
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, readFileSync, mkdirSync } from 'node:fs';
import { ok, done, DIR } from './lib.mjs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const S = `${DIR}/reel`;
mkdirSync(S, { recursive: true });
const env = { ...process.env, BB_REEL_OUT: `${S}/out` };
const reel = (...a) => spawnSync('python3', [`${REPO}/scripts/lib/reel.py`, ...a], { encoding: 'utf8', env });

const ff = spawnSync('ffmpeg', ['-version'], { encoding: 'utf8' });
if (ff.status !== 0){
  ok(true, 'skipped: no ffmpeg on this node, which bb reel says in its own words');
} else {
  execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
    '-i', 'color=c=navy:size=640x400:rate=10:duration=5',
    '-vf', "drawbox=x=100:y=100:w=300:h=150:color=orange:t=fill:enable='gte(t,2)',drawbox=x=420:y=40:w=150:h=300:color=white:t=fill:enable='gte(t,3.5)'",
    `${S}/cut.mp4`]);
  const r = reel('--video', `${S}/cut.mp4`, '--name', 'cut');
  const log = existsSync(`${S}/out/cut/frames.json`) ? JSON.parse(readFileSync(`${S}/out/cut/frames.json`, 'utf8')) : null;
  const ts = (log?.frames || []).map(f => f.t);
  ok(r.status === 0 && ts.length === 3 && ts[0] === 0 && Math.abs(ts[1] - 2) < 0.2 && Math.abs(ts[2] - 3.5) < 0.2
     && log.frames[1].change > 0.05 && log.frames[2].change > 0.05 && log.frames[0].change === 0,
     `a video with two changes reels to three frames at their times, with how much moved (${JSON.stringify(ts)}; ${
        (r.stderr || '').trim().split('\n').pop()?.slice(0, 80)})`);
  ok(existsSync(`${S}/out/cut/sheet.png`) && readFileSync(`${S}/out/cut/sheet.png`).length > 1000
     && /3 frames changed over 3.5s/.test(r.stderr || ''),
     '...tiled into one sheet, and the verb says how many and over how long');
  ok(/^\s+1\s+2\.0s\s+change/m.test(r.stdout || ''), '...and lists each frame with its time on the terminal');
}
// The sources refuse in their own words when the node lacks what they need.
const noSrc = reel('--name', 'x');
ok(noSrc.status !== 0 && /one source: --video FILE, --url URL, --emu \[PKG\] or --display :N/.test(noSrc.stderr || ''),
   `no source is refused naming the four (${(noSrc.stderr || '').trim().slice(0, 70)})`);
const noDisp = reel('--display', ':77', '--name', 'x');
ok(noDisp.status !== 0 && /no X display :77 on this node.*provisioner adds Xvfb and xdotool/.test(noDisp.stderr || ''),
   `a display the node does not have is refused, naming what the provisioner adds (${(noDisp.stderr || '').trim().slice(0, 80)})`);
const noVid = reel('--video', `${S}/none.mp4`);
ok(noVid.status !== 0 && /no such video/.test(noVid.stderr || ''), 'a video that is not there is refused');
// bb shot at rest: shots a quarter second apart until two match, so a page
// whose element lands late is pictured after it does. A page of this
// suite's own, served here, draws its heading after a second and a half;
// the immediate shot and the settled one differ, and two settled ones are
// the same bytes, since nothing on the page moves after that. The element
// lands inside the second bb shot waits for; a page that changes later than
// that is a page bb shot cannot know about, and --wait is for it.
{
  const { spawn } = await import('node:child_process');
  const { writeFileSync } = await import('node:fs');
  const web = `${S}/web`; mkdirSync(web, { recursive: true });
  writeFileSync(`${web}/index.html`, '<!doctype html><body style="margin:0;background:#fff">'
    + '<script>setTimeout(() => { document.body.innerHTML = "<h1 style=\'font:48px sans-serif\'>late</h1>"; }, 700)</script></body>');
  const port = 30000 + Math.floor(Math.random() * 20000);
  const srv = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1'], { cwd: web, stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1200));
  const shot = (file, ...flags) => spawnSync('bash', [`${REPO}/scripts/bb`, 'shot', `http://127.0.0.1:${port}/`, file, ...flags],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_PORT: '1' } });
  const now = shot(`${S}/now.png`, '--now'), one = shot(`${S}/one.png`, '--settle'), two = shot(`${S}/two.png`, '--settle');
  srv.kill();
  const bytes = f => existsSync(f) ? readFileSync(f) : Buffer.alloc(0);
  ok(now.status === 0 && one.status === 0 && two.status === 0 && bytes(`${S}/one.png`).length > 0
     && !bytes(`${S}/now.png`).equals(bytes(`${S}/one.png`)) && bytes(`${S}/one.png`).equals(bytes(`${S}/two.png`)),
     `bb shot --settle pictures a page after its late element lands, and --now pictures it before (${
        [now, one, two].map(r => r.status).join('/')}; ${(one.stderr || '').trim().slice(0, 60)})`);
}
await done();
