// The cover that hides the white flash when a terminal pane appears.
//
// The flash is the frame's document existing with no background of its own
// (ttyd colors `.xterm-viewport` and nothing above it), which a browser paints
// as a white canvas, over whatever the iframe element underneath is set to.
// Firefox on Android does it unconditionally.
//
// The cover used to come off on a fixed 350ms timer, a guess with a wide
// margin around it. It now closes the gap instead: the frame is same-origin
// (it is proxied through this server), so its <html> is given the pane's own
// color and the cover comes off on the next frame. The clock is only for a
// frame that cannot be reached at all.
//
// Driven against synthetic frames rather than a real terminal: the harness
// runs no ttyd, and what is under test is the release rule.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);

// A slot shaped like a pane's. `src` mimics what a terminal frame is: a
// document with no background of its own, exactly like ttyd's.
const build = src => page.evaluate(src => {
  document.querySelectorAll('#veiltest').forEach(n => n.remove());
  const slot = document.createElement('div');
  slot.id = 'veiltest'; slot.className = 'slot';
  const f = document.createElement('iframe');
  const v = document.createElement('i'); v.className = 'veil';
  slot.append(f, v); document.body.appendChild(slot);
  const done = new Promise(r => { f.onload = () => r(true); });
  if (src) f.src = src; else f.srcdoc = '<html><body><div>x</div></body></html>';
  return done;
}, src);

const veilState = () => page.evaluate(() => {
  const v = document.querySelector('#veiltest .veil');
  return !v ? 'removed' : v.classList.contains('gone') ? 'fading' : 'covering';
});
const lifted = () => page.waitForFunction(() => {
  const v = document.querySelector('#veiltest .veil');
  return !v || v.classList.contains('gone');
}, { timeout: 3000 });

// ---- the frame it can reach --------------------------------------------
await build();
ok(await page.$eval('#veiltest iframe',
     f => getComputedStyle(f.contentDocument.documentElement).backgroundColor
          === 'rgba(0, 0, 0, 0)'),
   'a terminal frame starts with no background of its own: this is the flash');

const t0 = Date.now();
await page.evaluate(() => unveil(document.querySelector('#veiltest iframe')));
await lifted();
const took = Date.now() - t0;
ok(await page.$eval('#veiltest iframe',
     f => getComputedStyle(f.contentDocument.documentElement).backgroundColor
          === 'rgb(43, 43, 43)'),
   'unveil gives it the pane color, so there is no white left to paint');
ok(took < 120, `...and the cover comes off at once (${took}ms, not the old 350ms floor)`);
await page.waitForFunction(() => !document.querySelector('#veiltest .veil'), { timeout: 3000 });
ok(await veilState() === 'removed', '...then takes itself out of the pane');

// ---- the frame it cannot ------------------------------------------------
// An opaque origin: contentDocument throws, nothing can be dressed, and the
// clock is all there is. This is the proxy-error and disagreeing-engine case.
await build('data:text/html,<p>opaque');
const t1 = Date.now();
await page.evaluate(() => unveil(document.querySelector('#veiltest iframe')));
await page.waitForTimeout(150);
ok(await veilState() === 'covering', 'a frame that cannot be reached stays covered');
await lifted();
const held = Date.now() - t1;
ok(held > 300 && held < 900, `...until the clock backstop (${held}ms)`);

// ---- a pane torn down mid-cover ----------------------------------------
await build('data:text/html,<p>opaque');
await page.evaluate(() => {
  unveil(document.querySelector('#veiltest iframe'));
  document.querySelector('#veiltest').remove();
});
await page.waitForTimeout(600);
ok(page.errors.length === 0, 'a pane replaced while covered raises nothing');

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
