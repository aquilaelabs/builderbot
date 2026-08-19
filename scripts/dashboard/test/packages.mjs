// The Tools card and its package manager: the card carries both the findings
// report and the packages `bb sdk` can install, the modal lists what is
// installed and where, and ticking rows installs or removes them through a
// server-side job. The harness's bb stub makes and removes directories rather
// than downloading gigabytes, so the whole round trip runs in a second.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { existsSync } from 'node:fs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the card ----------------------------------------------------------
// The heading carries a chevron alongside its text, so match the text only.
ok((await page.$eval('.card[data-card="findings"] h2', h => h.textContent.trim())).startsWith('Tools'),
   'the findings card is the Tools card now');
ok(await page.$eval('#bFindings', b => !b.hidden) && await page.$eval('#bPkgs', b => !b.hidden),
   'it keeps the findings button and gains the packages one');

// ---- the modal ---------------------------------------------------------
await page.click('#bPkgs');
await page.waitForFunction(() => document.querySelectorAll('#pkgList .pkg').length > 0);
const rows = () => page.$$eval('#pkgList .pkg', ls => ls.map(l => ({
  name: l.querySelector('input').value,
  installed: l.querySelector('.where').classList.contains('on'),
  where: l.querySelector('.where').textContent.trim(),
})));
let list = await rows();
ok(list.length >= 6 && list.some(r => r.name === 'flutter') && list.some(r => r.name === 'android:emulator'),
   'the modal lists the toolchains and the android packages');
ok(list.every(r => !r.installed) && list.every(r => r.where === 'not installed'),
   'a scratch root starts with nothing installed');
ok((await page.$eval('#pkgWhere', el => el.textContent)).includes(`${DIR}/sdk`),
   'it says which root things are installed into');

// ---- install two, watch them land --------------------------------------
await page.check('#pkgList input[value="flutter"]');
await page.check('#pkgList input[value="android:emulator"]');
await page.click('#pkgInstall');
await page.waitForFunction(() => [...document.querySelectorAll('#pkgList .where')]
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
ok(!(await page.$eval('#pkgLogWrap', el => el.hidden)), 'the progress log appears');

// ---- remove one --------------------------------------------------------
await page.uncheck('#pkgList input[value="android:emulator"]');
await page.click('#pkgRemove');
await page.waitForFunction(() => [...document.querySelectorAll('#pkgList .where')]
  .filter(w => w.classList.contains('on')).length === 1, { timeout: 30000 });
list = await rows();
ok(!list.find(r => r.name === 'flutter').installed
   && list.find(r => r.name === 'android:emulator').installed,
   'removing the ticked one leaves the other alone');
ok(!existsSync(`${DIR}/sdk/flutter`), '...and it is gone from disk');

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

await page.click('#pkgClose');
ok(await page.$eval('#pkgmodal', el => el.hidden), 'Close closes it');

const errs = page.errors.filter(e => !/status of 400/.test(e));
ok(errs.length === 0, `zero console errors${errs.length ? ' — ' + errs.join(' | ') : ''}`);
await done(browser);
