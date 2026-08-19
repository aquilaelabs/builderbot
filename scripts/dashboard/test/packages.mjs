// The Tools card and its package manager. Its own card, above the findings
// one: a package manager and a scanner report answer different questions,
// and only the report depends on /reports existing. Additional packages
// opens as a document TAB — installing an SDK runs for minutes, so it
// belongs on the strip rather than in a dialog to dismiss. The harness's bb
// stub makes and removes directories rather than downloading gigabytes, so
// the whole round trip runs in a second.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { existsSync } from 'node:fs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the card ----------------------------------------------------------
// The heading carries a chevron alongside its text, so match the text only.
ok((await page.$eval('.card[data-card="tools"] h2', h => h.textContent.trim())).startsWith('Tools'),
   'Tools is a card of its own');
ok((await page.$eval('.card[data-card="findings"] h2', h => h.textContent.trim())).startsWith('Static analysis'),
   '...and the findings card is still the findings card');
ok(await page.$$eval('.side .card[data-card]', cs => {
     const k = cs.map(c => c.dataset.card);
     return k.indexOf('tools') >= 0 && k.indexOf('tools') < k.indexOf('findings');
   }), 'Tools sits above it');
ok(await page.$eval('.card[data-card="tools"] #bPkgs', b => !b.hidden)
   && await page.$eval('.card[data-card="findings"] #bFindings', b => !b.hidden),
   'each card carries its own button');

// ---- the tab -----------------------------------------------------------
await page.click('#bPkgs');
await page.waitForFunction(() => document.querySelectorAll('.doc .pkg').length > 0);
ok(await page.evaluate(() => tabs.some(t => t.kind === 'packages')
     && tabOf(panes[active])?.kind === 'packages'),
   'Additional packages opens a tab, and lands on it');
ok(await page.$eval('.pane .bar [data-reload]', b => b.dataset.reload) === 'packages',
   'the pane bar offers a reload, like the findings report');
const rows = () => page.$$eval('.doc .pkg', ls => ls.map(l => ({
  name: l.querySelector('input').value,
  installed: l.querySelector('.where').classList.contains('on'),
  where: l.querySelector('.where').textContent.trim(),
})));
let list = await rows();
ok(list.length >= 6 && list.some(r => r.name === 'flutter') && list.some(r => r.name === 'android:emulator'),
   'the tab lists the toolchains and the android packages');
ok(list.every(r => !r.installed) && list.every(r => r.where === 'not installed'),
   'a scratch root starts with nothing installed');
ok((await page.$eval('.pkghead', el => el.textContent)).includes(`${DIR}/sdk`),
   'it says which root things are installed into');

// ---- install two, watch them land --------------------------------------
await page.check('.doc .pkg input[value="flutter"]');
await page.check('.doc .pkg input[value="android:emulator"]');
// The ticks live outside the DOM, so a redraw — one arrives every two
// seconds while a job runs — must not quietly clear the selection.
await page.evaluate(() => loadPackages());
await page.waitForFunction(() => document.querySelectorAll('.doc .pkg').length > 0);
ok(await page.$$eval('.doc .pkg input:checked', is => is.length === 2),
   'a redraw keeps what was ticked');
await page.click('.doc [data-pkg="install"]');
await page.waitForFunction(() => [...document.querySelectorAll('.doc .where')]
  .filter(w => w.classList.contains('on')).length === 2, { timeout: 30000 });
list = await rows();
const flutter = list.find(r => r.name === 'flutter');
const emu = list.find(r => r.name === 'android:emulator');
ok(flutter.installed && flutter.where.includes(`${DIR}/sdk/flutter`),
   'flutter installs to the SDK root, and the row says where');
ok(emu.installed && emu.where.includes(`${DIR}/androidsdk/emulator`),
   'an android package resolves to its place in the SDK tree');
ok(existsSync(`${DIR}/sdk/flutter`) && existsSync(`${DIR}/androidsdk/emulator`),
   '...and both really exist on disk');
ok(await page.$('.pkglog') !== null, 'the progress log appears');
// The ticks are the operator's, and a poll every two seconds must not
// quietly clear them mid-install.

// A finished install lets go of its ticks, so the next click cannot act on
// what was just dealt with — Remove especially.
ok(await page.$$eval('.doc .pkg input', is => is.every(i => !i.checked)),
   'a finished job clears the selection it consumed');

// ---- versions and updates ----------------------------------------------
// The installed version is local knowledge and shows without being asked;
// whether something newer exists is a network question, and until it is asked
// no row claims anything.
ok((await page.$$eval('.doc .pkg .nm .pill', ps => ps.map(p => p.textContent)))
     .some(t => t === '1.0'), 'installed versions show without a check');
ok(await page.$$eval('.doc .pkg .upd', us => us.length === 0),
   'no update claims before a check');
await page.click('.doc [data-pkg="check"]');
await page.waitForFunction(() => document.querySelector('.doc .pkg .upd') !== null,
                           { timeout: 30000 });
const upd = await page.$$eval('.doc .pkg', ls => ls
  .filter(l => l.querySelector('.upd'))
  .map(l => l.querySelector('input').value));
ok(upd.length === 1 && upd[0] === 'flutter',
   'the check marks exactly the package whose upstream moved');
ok(await page.$eval('.doc .pkg input[value="android:emulator"]', i => i.disabled),
   'installed and current: the tick is dead, there is nothing to do');
ok(!(await page.$eval('.doc .pkg input[value="flutter"]', i => i.disabled)),
   '...but an update brings its tick back');
ok(!(await page.$eval('.doc .pkg input[value="swift"]', i => i.disabled)),
   'and something not installed at all is always tickable');
ok((await page.$eval('.doc .pkg .upd', el => el.textContent)).includes('→ 2.0'),
   '...and says which version it would move to');
// Update runs like the others: a job, a log, and the ticks it consumed.
await page.check('.doc .pkg input[value="flutter"]');
await page.click('.doc [data-pkg="install"]');
await page.waitForFunction(() => (document.querySelector('.pkglog')?.textContent || '').includes('updated flutter'),
                           { timeout: 30000 });
ok(true, 'Install selected updates a package that is already installed');
ok(await page.$$eval('.doc [data-pkg]', bs => bs.every(b => b.textContent.indexOf('Remove') < 0)),
   'there is no bulk remove button to mis-click');

// ---- uninstall is per row, and asks ------------------------------------
ok(await page.$$eval('.doc .pkg', ls => ls.filter(l => l.querySelector('[data-rm]')).length) === 2,
   'every installed package carries its own uninstall control');
ok(await page.$('.doc .pkg:not(:has([data-rm])) [data-rm]') === null,
   '...and packages that are not installed do not');
const nd = page.dialogs.length;
await page.click('.doc [data-rm="android:emulator"]');
ok(page.dialogs.length === nd + 1 && page.dialogs[nd].includes('Uninstall'),
   'uninstalling asks first');
await page.waitForFunction(() => [...document.querySelectorAll('.doc .where')]
  .filter(w => w.classList.contains('on')).length === 1, { timeout: 30000 });
list = await rows();
ok(!list.find(r => r.name === 'android:emulator').installed
   && list.find(r => r.name === 'flutter').installed,
   'removing the ticked one leaves the other alone');
ok(!existsSync(`${DIR}/androidsdk/emulator`), '...and it is gone from disk');

// ---- what the endpoint refuses ----------------------------------------
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/packages', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return r.status;
}, body);
ok(await post({ action: 'install', names: ['flutter; rm -rf /'] }) === 400,
   'a name that is not in the catalog is refused');
ok(await post({ action: 'install', names: [] }) === 400, 'an empty selection is refused');
ok(await post({ action: 'sudo', names: ['flutter'] }) === 400, 'an unknown action is refused');

// It is a tab like any other: minimizing it leaves the strip, and the saved
// layout brings it back with its own data rather than an empty pane.
await page.evaluate(() => hideTab(tabs.find(t => t.kind === 'packages').id));
ok(await page.evaluate(() => !tabs.some(t => t.kind === 'packages')), 'the tab minimizes away');
await page.click('#bPkgs');
await page.waitForFunction(() => document.querySelectorAll('.doc .pkg').length > 0);
ok(true, 'and reopens from the card');

const errs = page.errors.filter(e => !/status of 400/.test(e));
ok(errs.length === 0, `zero console errors${errs.length ? ' — ' + errs.join(' | ') : ''}`);
await done(browser);
