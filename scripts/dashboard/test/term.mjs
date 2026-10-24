// BuilderBot's own terminal (R133): with the switch on, a shell tab is drawn
// by xterm.js in the page and joined to /termws, which runs bb-tty in a pty
// on this controller as ttyd did. What is typed reaches the shell and what
// it prints reaches the screen; the screen fits its box and the pty follows;
// a terminal that ends says why under it, and Reconnect opens it again on
// the same tmux session; a closed tab's socket goes with it; the switch off,
// the same tab is ttyd's frame again. Driven through the page, as a person
// at the dock would.
import { launch, newPage, ok, done, ready, finger, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);

const setting = on => page.evaluate(async on => {
  const r = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                            body: JSON.stringify({ set: { own_terminal: on } }) });
  await refresh();
  return r.status;
}, on);
ok(await setting(true) === 200 && await page.evaluate(() => state.term_own === true),
   'the switch is on, and the page is told so in its status');

// One shell, in the dock.
const id = await page.evaluate(() => { openTab({kind: 'term', arg: 'sh:7:alpha', label: 'own'});
                                       return tabs.find(t => t.arg === 'sh:7:alpha').id; });
await page.evaluate(id => { panes[1] = id; dockUp = true; render(); }, id);
await page.waitForFunction(() => document.querySelector('#pane1 .slot.on.ownterm .xterm'), null, { timeout: 20000 });
ok(await page.evaluate(() => !document.querySelector('#pane1 .slot.on iframe')),
   'the shell tab is drawn by xterm in the page, with no ttyd frame');

// What the screen shows, read off xterm's own buffer.
const screen = () => page.evaluate(() => {
  const rec = [...TERMS.values()].find(r => r.el.isConnected && r.term);
  if (!rec) return '';
  const b = rec.term.buffer.active, out = [];
  for (let i = 0; i < b.length; i++) out.push(b.getLine(i)?.translateToString(true) || '');
  return out.join('\n');
});
const waitFor = async (re, ms = 20000) => {
  const end = Date.now() + ms;
  while (Date.now() < end){
    if (re.test(await screen())) return true;
    await new Promise(r => setTimeout(r, 200));
  }
  return false;
};

// The text is inset from the pane's edges, and the rows still fit: the
// last row's bottom inside the box.
const inset = await page.evaluate(() => {
  const host = document.querySelector('#pane1 .slot.on .xhost'), x = host.querySelector('.xterm-screen');
  const h = host.getBoundingClientRect(), r = x.getBoundingClientRect();
  return { left: Math.round(r.left - h.left), top: Math.round(r.top - h.top), fits: r.bottom <= h.bottom + 0.5 };
});
ok(inset.left >= 8 && inset.top >= 8 && inset.fits, `the text sits off the pane's edges and fits in it (${JSON.stringify(inset)})`);

// Typing goes down the socket to the shell; its answer comes back up.
await page.click('#pane1 .slot.on .xterm');
await page.keyboard.type('echo own-$((40+2))-terminal\n');
ok(await waitFor(/own-42-terminal/), 'what is typed reaches the shell, and what it prints reaches the screen');

// The pty is the size of the box: stty in tmux's pane says what xterm
// fitted, a row short for tmux's status line.
const dims = await page.evaluate(() => { const r = [...TERMS.values()].find(r => r.term); return [r.term.rows, r.term.cols]; });
await page.keyboard.type('stty size\n');
ok(await waitFor(new RegExp(`\\b(${dims[0]}|${dims[0] - 1}) ${dims[1]}\\b`)), `the pty is the size xterm fitted to its box (${dims.join(' ')})`);

// Ended from inside: the line under it says so, and Reconnect attaches the
// same tmux session again.
await page.keyboard.type('tmux detach\n');
await page.waitForFunction(() => !document.querySelector('#pane1 .slot.on .xend')?.hidden, null, { timeout: 20000 });
const why = await page.$eval('#pane1 .slot.on .xwhy', e => e.textContent);
ok(/ended/.test(why), `a terminal that ends says so under the screen (${why})`);
await page.click('#pane1 .slot.on .xagain');
await page.waitForFunction(() => document.querySelector('#pane1 .slot.on .xend')?.hidden, null, { timeout: 20000 });
ok(await waitFor(/own-42-terminal/), '...and Reconnect attaches the same session, its screen as it was');

// The keys bar types down the same socket (step 5): a line typed, then the
// bar's Enter, runs it; nothing went by the server's tmux.
const keysAsked = [];
page.on('request', r => { if (r.url().includes('/api/keys')) keysAsked.push(r.url()); });
await page.click('#pane1 .slot.on .xterm');
await page.keyboard.type('echo kb-$((6*7))');
await page.evaluate(() => { active = 1; return sendKey('enter'); });
ok(await waitFor(/kb-42/) && !keysAsked.length, `the keys bar's Enter goes down the terminal's own socket (${keysAsked.length} asked of the server)`);

// The look is the person's (step 10): their Profile's size, cursor and
// colors reach the open terminal; a project's colors in their own settings
// for it win there.
{
  const opts = () => page.evaluate(() => { const r = [...TERMS.values()].find(r => r.t.arg === 'sh:7:alpha' && r.term);
    return { size: r.term.options.fontSize, cursor: r.term.options.cursorStyle, bg: r.term.options.theme.background }; });
  const own = async prefs => page.evaluate(async prefs => {
    const r = await (await fetch('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'prefs', prefs }) })).json();
    await refresh();
    return { r, look: state.term_look };
  }, prefs);
  const saved = await own({ term: { size: 16, cursor: 'bar', blink: false, scheme: 'light' } });
  await page.waitForFunction(() => [...TERMS.values()].some(r => r.t.arg === 'sh:7:alpha' && r.term?.options.fontSize === 16), null, { timeout: 10000 }).catch(() => {});
  const mine = await opts();
  // ...and the room around the text wears the terminal's own color.
  const pad = await page.evaluate(() => getComputedStyle(document.querySelector('#pane1 .slot.on.ownterm')).backgroundColor);
  const said = await page.evaluate(async () => (await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', term_scheme: 'red' }) })).status);
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => [...TERMS.values()].some(r => r.t.arg === 'sh:7:alpha' && r.term?.options.theme.background === '#2c1416'), null, { timeout: 10000 }).catch(() => {});
  const there = await opts();
  const padThere = await page.evaluate(() => getComputedStyle(document.querySelector('#pane1 .slot.on.ownterm')).backgroundColor);
  ok(pad === 'rgb(250, 250, 250)' && padThere === 'rgb(44, 20, 22)',
     `the room around the text changes color with the terminal (${pad} then ${padThere})`);
  ok(mine.size === 16 && mine.cursor === 'bar' && mine.bg === '#fafafa' && said === 200 && there.bg === '#2c1416' && there.size === 16,
     `a terminal takes its person's look, and their colors for its project over it (${JSON.stringify(mine)} then ${JSON.stringify(there)})`);
  await page.evaluate(async () => fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', term_scheme: '' }) }));
}

// On a phone (step 11): a finger dragged down scrolls back through a
// shell's history, by the line, in tmux's copy mode; a press held on a word
// selects it, with grips and Copy; Copy puts it on the clipboard.
{
  const phone = await newPage(browser, { viewport: { width: 393, height: 800 }, hasTouch: true, isMobile: true });
  await phone.goto(URL);
  await ready(phone);
  await phone.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new globalThis.URL(URL).origin });
  await phone.evaluate(() => { openTab({kind: 'term', arg: 'sh:9:alpha', label: 'thumb'});
    panes[1] = tabs.find(t => t.arg === 'sh:9:alpha').id; dockUp = true; render(); });
  await phone.waitForFunction(() => document.querySelector('#pane1 .slot.on.ownterm .xterm-screen'), null, { timeout: 20000 });
  const shown = () => phone.evaluate(() => {
    const r = [...TERMS.values()].find(r => r.t.arg === 'sh:9:alpha' && r.term), b = r.term.buffer.active, out = [];
    for (let i = 0; i < r.term.rows; i++) out.push(b.getLine(b.viewportY + i)?.translateToString(true) || '');
    return out;
  });
  const until = async (fn, ms = 15000) => { const end = Date.now() + ms;
    while (Date.now() < end){ const got = fn(await shown()); if (got) return got; await new Promise(r => setTimeout(r, 200)); }
    return null; };
  await phone.evaluate(() => { const r = [...TERMS.values()].find(r => r.t.arg === 'sh:9:alpha'); r.term.focus(); });
  await phone.keyboard.type('seq 1 300; echo pick-me-word\n');
  await until(rows => rows.some(l => /^pick-me-word/.test(l)));
  const asked = [];
  phone.on('request', r => { if (r.url().includes('/api/keys')) asked.push(r.postData() || ''); });
  const box = await phone.$eval('#pane1 .slot.on .xterm-screen', e => { const b = e.getBoundingClientRect(); return { x: b.left + b.width / 2, top: b.top + 20, h: b.height }; });
  // Under a full run's load one drag's lines did not always reach the
  // screen in time (B328): a second drag, said in the result.
  const scrolled = rows => rows.some(l => /\[\d+\/\d+\]/.test(l)) && !rows.some(l => /^pick-me-word/.test(l)) && rows;
  await finger(phone, box.x, box.top, box.x, box.top + box.h * 0.6);
  let back = await until(scrolled, 5000), drags = 1;
  if (!back){ await finger(phone, box.x, box.top, box.x, box.top + box.h * 0.6); drags = 2; back = await until(scrolled); }
  ok(back && asked.some(b => /"lineup"/.test(b)),
     `a finger dragged down scrolls a shell back into its history (${drags} drag${drags === 1 ? '' : 's'}, ${asked.length} asked: ${asked[0] || ''})`);
  // Up again, past the bottom: copy mode ends by itself.
  await finger(phone, box.x, box.top + box.h * 0.9, box.x, box.top);
  await finger(phone, box.x, box.top + box.h * 0.9, box.x, box.top);
  const home = await until(rows => !rows.some(l => /\[\d+\/\d+\]/.test(l)) && rows.some(l => /^pick-me-word/.test(l)));
  ok(home, 'a finger dragged up brings it back to the newest, out of copy mode');
  // The word, found on the screen, pressed and held.
  const at = await phone.evaluate(() => {
    const r = [...TERMS.values()].find(r => r.t.arg === 'sh:9:alpha'), b = r.term.buffer.active;
    for (let i = 0; i < r.term.rows; i++){
      const l = b.getLine(b.viewportY + i)?.translateToString(true) || '';
      if (/^pick-me-word/.test(l)){ const c = termCell(r); return { x: c.b.left + 4.5 * c.w, y: c.b.top + (i + 0.5) * c.h }; }
    }
    return null;
  });
  if (at) await finger(phone, at.x, at.y, at.x, at.y, 800);
  await phone.waitForTimeout(800);
  const picked = await phone.evaluate(() => ({ sel: [...TERMS.values()].find(r => r.t.arg === 'sh:9:alpha').term.getSelection(),
    grips: document.querySelectorAll('#pane1 .slot.on .xsel .xgrip').length, copy: !!document.querySelector('#pane1 .slot.on .xsel .xcopy') }));
  ok(at && picked.sel === 'pick-me-word' && picked.grips === 2 && picked.copy,
     `a press held on a word selects it, with a grip at each end and Copy (${JSON.stringify(picked)})`);
  await phone.click('#pane1 .slot.on .xsel .xcopy').catch(() => {});
  const clip = await phone.evaluate(() => navigator.clipboard.readText().catch(e => 'unread: ' + e.message));
  const gone = await phone.evaluate(() => !document.querySelector('#pane1 .slot.on .xsel'));
  ok(clip === 'pick-me-word' && gone, `Copy puts the word on the clipboard and puts the selection away (${clip})`);
  await phone.evaluate(() => dropTab(tabs.find(t => t.arg === 'sh:9:alpha').id));
  await phone.close();
}

// A tab its node sends back to ttyd (4001: an agent with no terminal of its
// own) is drawn again as ttyd's frame, not left an empty slot.
await page.evaluate(id => { tabOf(id).ttyd = true; render(); }, id);
const back = await page.waitForSelector('#pane1 .slot.on iframe', { timeout: 10000 }).then(() => true, () => false);
ok(back && await page.evaluate(() => !document.querySelector('#pane1 .slot.on.ownterm')),
   'a tab sent back to ttyd is redrawn as its frame');
await page.evaluate(id => { delete tabOf(id).ttyd; render(); }, id);
await page.waitForSelector('#pane1 .slot.on.ownterm .xterm', { timeout: 20000 });

// The socket and the shell are one: closing the tab closes the socket.
const before = await page.evaluate(() => [...TERMS.values()].filter(r => r.t.arg === 'sh:7:alpha').length);
await page.evaluate(id => dropTab(id), id);
await page.waitForFunction(() => ![...TERMS.values()].some(r => r.t.arg === 'sh:7:alpha'), null, { timeout: 10000 }).catch(() => {});
const after = await page.evaluate(() => [...TERMS.values()].filter(r => r.t.arg === 'sh:7:alpha').map(r => r.key));
ok(before === 1 && after.length === 0, `closing the tab closes its terminal (${before}: ${JSON.stringify(after)})`);

// Off again: a shell tab is ttyd's frame, as before.
await setting(false);
const id2 = await page.evaluate(() => { openTab({kind: 'term', arg: 'sh:8:beta', label: 'ttyd'});
                                        return tabs.find(t => t.arg === 'sh:8:beta').id; });
await page.evaluate(id => { panes[1] = id; dockUp = true; render(); }, id2);
await page.waitForSelector('#pane1 .slot.on iframe', { timeout: 20000 });
ok(await page.evaluate(() => !document.querySelector('#pane1 .slot.on.ownterm')),
   'with the switch off a shell tab is ttyd\'s frame again');
await page.evaluate(id => dropTab(id), id2);

await done(browser);
