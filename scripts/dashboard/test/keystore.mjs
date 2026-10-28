// An unlock that gives up less (R158 step 5) and a key of the person's own
// (R157), on the page: Profile's Your key store shows who holds the key and
// the window, a token given to a project is opened per use and listed under
// Uses of your tokens, Hold the key yourself with a key the person keeps
// locks the store until that key unlocks it (the Git view says so while it
// is locked), a passkey that answers PRF holds it too where this Chrome's
// virtual authenticator does PRF, and Give the key back moves it under the
// install key again.
import { URL as BASE, launch, newPage, done, ok, settled, patience } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser);
await page.goto(BASE);
await page.waitForFunction(() => typeof state !== 'undefined' && state && state.repos);
const keys = body => page.evaluate(async b => (await (await postJSON('/api/keys', b)).json()), body);

// A token of the person's, given to alpha (the fixture's project).
const given = await page.evaluate(async () => (await (await postJSON('/api/rename', { name: 'alpha', token: 'ghp_suiteTokenValue0123' })).json()).catch(() => ({}));
let mine = await keys({ action: 'mine' });
ok(!given.error && (mine.forges || []).length >= 1, `a token given to alpha is in the store (${given.error || (mine.forges || []).length + ' entries'})`);
if (!mine.sealing){ ok(true, 'this fixture has no install key: nothing is sealed, and the store has nothing to unlock (skipped)'); await done(browser); process.exit(0); }
ok(mine.own === false && mine.locked === false && mine.for === 3600, `the store is under the install key, open, an hour's window (${JSON.stringify({ own: mine.own, locked: mine.locked, for: mine.for })})`);

// Profile draws it: Held by, the window picker, Lock, Hold the key yourself.
await page.evaluate(() => openProfileTab());
await page.waitForSelector('.doc details[data-sect="profile:mykey"]', { timeout: patience(20000) });
await settled(page);
const drawn = await page.evaluate(() => ({
  held: [...document.querySelectorAll('.doc details[data-sect="profile:mykey"] .fact, .doc details[data-sect="profile:mykey"] dt, .doc details[data-sect="profile:mykey"] *')].some(e => /Held by/.test(e.textContent)),
  pick: !!document.querySelector('#ksFor'), lock: !!document.querySelector('#bKsLock'), own: !!document.querySelector('#bKsOwn'),
  uses: !!document.querySelector('.doc details[data-sect="profile:uses"]'),
}));
ok(drawn.held && drawn.pick && drawn.lock && drawn.own && drawn.uses, `Profile shows who holds the key, the window, Lock, Hold the key yourself and the uses (${JSON.stringify(drawn)})`);

// The window picked is kept; Lock lets go.
ok((await keys({ action: 'unlock-for', for: 900 })).for === 900, 'the window picked is kept with the key');
ok((await keys({ action: 'unlock-for', for: 123 })).error !== undefined, '...and only one of the four windows is taken');

// A key the person keeps: the store moves under it and is open; Lock shuts it; the wrong key is refused; the right one opens it.
const KEY = 'ab'.repeat(32);
const moved = await keys({ action: 'own-key', key: KEY, keep: [] });
ok(moved.ok === true && moved.unlocked === true, `Hold the key yourself with a key kept: moved and open (${moved.error || 'ok'})`);
mine = await keys({ action: 'mine' });
ok(mine.own === true && mine.how === 'key' && mine.locked === false && !!mine.fingerprint, 'the store says it is under a key the person keeps, open, with its fingerprint');
ok((await keys({ action: 'change-mine' })).error !== undefined, 'Change key is refused while a key of the person\'s own holds the store');
await keys({ action: 'lock' });
mine = await keys({ action: 'mine' });
ok(mine.locked === true && !!mine.fingerprint, 'Lock shuts it, and the fingerprint still shows');
const st = await page.evaluate(async () => (await (await fetch('/api/status')).json()).store);
ok(st && st.own === true && st.locked === true, 'the status payload says the store is the person\'s own and locked, for the page');
// The Git view says why a push would wait.
const gitSaid = await page.evaluate(async () => (await (await fetch('/api/git?project=alpha&what=status')).json()).token || {});
ok(/locked/.test(gitSaid.why || ''), `the Git view's line says the store is locked (${(gitSaid.why || '').slice(0, 60)})`);
ok((await keys({ action: 'unlock', key: 'cd'.repeat(32) })).error !== undefined, 'another key does not open it');
const un = await keys({ action: 'unlock', key: KEY, for: 28800 });
ok(un.ok === true && un.for === 28800, 'the key kept opens it, for eight hours');
const uses = (await keys({ action: 'uses' })).uses || [];
ok(uses.some(u => u.why === 'unlocked') && uses.some(u => u.why === 'locked'), `the unlock and the lock are on the uses list (${uses.slice(0, 4).map(u => u.why).join(', ')})`);
// Back under the install key.
const back = await keys({ action: 'own-back' });
ok(back.ok === true && (await keys({ action: 'mine' })).own === false, 'Give the key back moves it under the install key again');

// A passkey that answers PRF, where this Chrome's virtual authenticator does.
const cdp = await page.context().newCDPSession(page);
await cdp.send('WebAuthn.enable');
let prfOk = false;
try {
  await cdp.send('WebAuthn.addVirtualAuthenticator', { options: {
    protocol: 'ctap2', ctap2Version: 'ctap2_1', transport: 'internal', hasResidentKey: true, hasUserVerification: true,
    isUserVerified: true, automaticPresenceSimulation: true, hasPrf: true } });
  prfOk = true;
} catch (e) { ok(true, `this Chrome's virtual authenticator does no PRF, so the passkey half is not proved here (${String(e.message || e).slice(0, 60)})`); }
if (prfOk){
  await page.evaluate(() => openProfileTab());
  await page.waitForSelector('.doc [data-tf="passkey-add"]', { timeout: patience(20000) });
  await page.click('.doc [data-tf="passkey-add"]');
  await page.waitForSelector('.modal:not([hidden]) input', { timeout: patience(15000) });
  await page.fill('.modal:not([hidden]) input', 'prf key');
  await page.click('.modal:not([hidden]) button:has-text("Save")');
  await page.waitForFunction(() => (profile?.two_factor?.passkeys || []).some(k => k.name === 'prf key'), null, { timeout: patience(15000) });
  const pk = await page.evaluate(() => (profile?.two_factor?.passkeys || []).find(k => k.name === 'prf key'));
  if (!pk.prf){ ok(true, 'the virtual authenticator made a passkey without PRF: the passkey half is not proved here'); }
  else {
    // The move with the passkey, driven as the page does it: the PRF answer relayed with the passkey's proof.
    const got = await page.evaluate(async () => {
      const s = await keyStoreSecret('', 'passkey');
      if (!s) return { error: 'no secret' };
      return (await (await postJSON('/api/keys', { action: 'own-key', ...s, keep: [] })).json());
    });
    ok(got.ok === true, `the passkey holds the key: the store moved under its PRF secret (${got.error || 'ok'})`);
    await keys({ action: 'lock' });
    const again = await page.evaluate(async () => {
      const s = await keyStoreSecret('', 'passkey');
      return s ? (await (await postJSON('/api/keys', { action: 'unlock', ...s })).json()) : { error: 'no secret' };
    });
    ok(again.ok === true, `...and unlocks it again (${again.error || 'ok'})`);
    ok((await keys({ action: 'own-back' })).ok === true, 'given back under the install key');
  }
}
await done(browser);
