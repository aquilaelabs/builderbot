// BuilderBot's own terminal (R133): with the switch on, a shell tab is drawn
// by xterm.js in the page and joined to /termws, which runs bb-tty in a pty
// on this controller as ttyd did. What is typed reaches the shell and what
// it prints reaches the screen; the screen fits its box and the pty follows;
// a terminal that ends says why under it, and Reconnect opens it again on
// the same tmux session; a closed tab's socket goes with it; the switch off,
// the same tab is ttyd's frame again. Driven through the page, as a person
// at the dock would.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';

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
  const said = await page.evaluate(async () => (await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', term_scheme: 'red' }) })).status);
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => [...TERMS.values()].some(r => r.t.arg === 'sh:7:alpha' && r.term?.options.theme.background === '#2c1416'), null, { timeout: 10000 }).catch(() => {});
  const there = await opts();
  ok(mine.size === 16 && mine.cursor === 'bar' && mine.bg === '#fafafa' && said === 200 && there.bg === '#2c1416' && there.size === 16,
     `a terminal takes its person's look, and their colors for its project over it (${JSON.stringify(mine)} then ${JSON.stringify(there)})`);
  await page.evaluate(async () => fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', term_scheme: '' }) }));
}

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
