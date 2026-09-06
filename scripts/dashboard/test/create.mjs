// New project: the button at the foot of the Projects card, the dialog, and
// /api/create behind it. The local path runs for real — git init in the
// scratch workspace, CLAUDE.md built from the checkout's template — while the
// clone path is tested up to its URL allow-list: the list is the thing under
// test, and a real clone would need GitHub on the other end.
import { launch, newPage, ok, done, ready, URL, DIR, animatedDuring } from './lib.mjs';
import { readFileSync, existsSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);

// Declared here, not down beside the allow-list tests where they began:
// the rename section above those uses them, and `const` in a module has a
// temporal dead zone rather than being hoisted.
const post = (body, api = '/api/create') => page.evaluate(async ([b, u]) => {
  const r = await fetch(u, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return r.status;
}, [body, api]);
// The same call, keeping the body: sanitizing is asserted on the name that
// comes back, which is the only place the answer actually exists.
const postJson = (body, api = '/api/create') => page.evaluate(async ([b, u]) => {
  const r = await fetch(u, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, [body, api]);

// ---- the dialog --------------------------------------------------------
ok(await page.$eval('#projects #bNewProj', b => b.textContent.includes('New project')),
   'New project sits at the foot of the Projects card');
await page.click('#bNewProj');
ok(await page.$eval('#pmodal', el => !el.hidden), 'the dialog opens');
const idle = () => page.evaluate(() => document.activeElement?.tagName || '');
ok(await idle() !== 'INPUT' && await idle() !== 'TEXTAREA',
   '...with the cursor in none of its fields');
ok(await page.$eval('#pUrlField', el => el.hidden), 'local repo is the default; no URL field');
const cloneSlide = await animatedDuring(page, () => page.click('#pClone'));
ok(await page.$eval('#pUrlField', el => !el.hidden)
   && await page.$eval('#pClone', b => b.classList.contains('on')),
   'clone mode shows the URL field and takes the green');
ok(cloneSlide.some(k => k.includes('pUrlField')),
   '...sliding in from its tab\'s side, like the view switch');
ok(await page.$eval('#pNameField', el => !el.hidden)
   && await page.$eval('#pAboutField', el => el.hidden),
   'clone mode asks for a name as well as the URL — only the notes come from the repo');
// The name follows the address, so the common case is still no typing...
await page.fill('#pUrl', 'https://github.com/owner/radarr.git');
ok(await page.$eval('#pName', el => el.value) === 'radarr',
   '...prefilled from the address, .git and all stripped off');
// ...and stops following the moment somebody wants two of the same repo.
await page.fill('#pName', 'radarr-4k');
await page.fill('#pUrl', 'https://github.com/owner/radarr');
ok(await page.$eval('#pName', el => el.value) === 'radarr-4k',
   '...but a name typed by hand is not overwritten by the next keystroke');
await page.fill('#pUrl', '');
await page.click('#pLocal');
ok(await page.$eval('#pNameField', el => !el.hidden), 'back to local keeps the name field');
// The preview says what the directory will be called, and only when that is
// not what was typed.
await page.fill('#pName', 'My New App');
ok(await page.$eval('#pNamePreview', el => !el.hidden && /My-New-App/.test(el.textContent)),
   'a name GitHub would rewrite is previewed as the directory it becomes');
await page.fill('#pName', 'plain');
ok(await page.$eval('#pNamePreview', el => el.hidden),
   '...and stays quiet when there is nothing to say');
// Put the field back as it was found: a mode switch does not clear it, only
// reopening does, and the refusal below needs the name genuinely empty or it
// submits a valid one and closes the dialog out from under everything after.
// Set rather than filled, because page.fill focuses the input and the very
// next assertion is that switching tabs leaves no cursor anywhere.
await page.$eval('#pName', el => { el.value = ''; el.blur(); });
// Neither tab puts a cursor anywhere. A focused field brings the on-screen
// keyboard up with it, over half of the dialog that just opened — so the
// field is picked by whoever wants to type in it.
ok(await idle() !== 'INPUT' && await idle() !== 'TEXTAREA',
   'switching to local leaves the keyboard down');
await page.click('#pClone');
ok(await idle() !== 'INPUT' && await idle() !== 'TEXTAREA',
   '...and so does switching to clone');
await page.click('#pLocal');

// Refusals keep the dialog open with the reason in place — nothing typed is
// lost to a mistake.
await page.click('#pCreate');
ok(await page.$eval('#pErr', el => el.textContent.includes('name')),
   'an empty name is refused in place');
// ...and does not outlive a mode switch, where it would sit over a form
// that no longer asks for a name.
await page.click('#pClone');
ok(await page.$eval('#pErrWrap', el => el.hidden), 'switching modes clears the stale error');
await page.click('#pLocal');
await page.fill('#pName', 'alpha');
await page.click('#pCreate');
await page.waitForFunction(() =>
  document.getElementById('pErr').textContent.includes('already exists'));
ok(await page.$eval('#pmodal', el => !el.hidden),
   'a taken name is refused with the reason, dialog still open');

// ---- a real local project ----------------------------------------------
await page.fill('#pName', 'zeta');
await page.fill('#pAbout', 'A widget frobnicator. Build with make.');
await page.click('#pCreate');
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 15000 });
await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
  .some(n => n.textContent === 'zeta'), { timeout: 15000 });
ok(true, 'the new project appears in the card');
ok(existsSync(`${DIR}/ws/zeta/.git`), 'zeta is a git repository');
const md = readFileSync(`${DIR}/ws/zeta/CLAUDE.md`, 'utf8');
const marker = md.indexOf('BUILDERBOT:ENV:END');
ok(marker > 0, 'its CLAUDE.md carries the environment block');
ok(md.indexOf('A widget frobnicator') > marker,
   '...with the given notes below the end marker');

// A project made after anything has been pinned is pinned itself. Without
// that it lands on disk and never reaches the sidebar — created, and to the
// operator indistinguishable from gone. Unpinning first is what brings the
// pins file into existence; while there is none, everything is pinned anyway
// and this would prove nothing.
await page.evaluate(() => setProjectPinned('beta', false));
await page.waitForFunction(
  () => ![...document.querySelectorAll('#projects .row .name')]
          .some(n => n.textContent.trim() === 'beta'), { timeout: 15000 });
await page.click('#bNewProj');           // zeta's create closed the dialog
await page.waitForSelector('#pmodal:not([hidden])');
await page.fill('#pName', 'pinme');
await page.click('#pCreate');
await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
  .some(n => n.textContent === 'pinme'), { timeout: 15000 });
ok(true, 'a project created while a pins file exists still reaches the sidebar');

// ---- renaming ----------------------------------------------------------
// The button is nothing; the migration is the job. A project's name is its key
// in a dozen stores, and every one of them fails the same quiet way when it is
// missed — the directory is there under its new name and its roadmap is not.
// The pins file is the one that is trivial to seed and to read back, so it
// stands in for the table: if the name moved there it moved by the same code
// path everywhere else.
ok(JSON.parse(readFileSync(`${DIR}/state/pinned-projects.json`, 'utf8')).includes('pinme'),
   'the pins file knows the project before the rename');
const rn = await postJson({ name: 'pinme', to: 'pinned-again' }, '/api/rename');
ok(rn.status === 200 && rn.body.name === 'pinned-again',
   'renaming answers with the name it actually made');
ok(existsSync(`${DIR}/ws/pinned-again/.git`) && !existsSync(`${DIR}/ws/pinme`),
   '...the directory moved, and nothing was left behind under the old name');
const pins = JSON.parse(readFileSync(`${DIR}/state/pinned-projects.json`, 'utf8'));
ok(pins.includes('pinned-again') && !pins.includes('pinme'),
   '...and the state keyed to the old name came with it');
ok(Array.isArray(rn.body.moved) && rn.body.moved.length > 0 && !rn.body.failed.length,
   '...reporting what moved rather than only that it worked');
await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
  .some(n => n.textContent === 'pinned-again'), { timeout: 15000 });
ok(true, '...and the row is the new name');

// The refusals. A name already taken, a project that is not there, and the
// name it already has — each answered rather than half-done.
ok(await post({ name: 'pinned-again', to: 'alpha' }, '/api/rename') === 400,
   'renaming onto a name already in the workspace is refused');
ok(await post({ name: 'nosuchproject', to: 'whatever' }, '/api/rename') === 400,
   'renaming something that is not a project is refused');
ok(await post({ name: 'pinned-again', to: 'pinned-again' }, '/api/rename') === 400,
   'renaming to the name it already has is refused');
ok(await post({ name: 'pinned-again', to: '///' }, '/api/rename') === 400,
   'a new name with nothing in it is refused');
// ...and a messy one is sanitized on the way through, exactly as creating is.
const rn2 = await postJson({ name: 'pinned-again', to: 'Two Words!' }, '/api/rename');
ok(rn2.status === 200 && rn2.body.name === 'Two-Words',
   'a new name goes through the same sanitizing a created one does');
ok(existsSync(`${DIR}/ws/Two-Words/.git`), '...and that is the directory');

await page.evaluate(() => setProjectPinned('beta', true));

// ---- the allow-lists ---------------------------------------------------
// Straight at the API: git accepts transports (ext:: runs commands) that must
// never get past the server, whatever the page's own form checks.
for (const url of ['https://evil.example/owner/repo', 'ext::sh -c id',
                   'file:///etc', 'https://github.com/owner-only',
                   'git@github.com:owner/repo extra'])
  ok(await post({ mode: 'clone', url }) === 400, `clone refused: ${url}`);
ok(!existsSync(`${DIR}/ws/repo`), 'a refused clone leaves no directory behind');
// The name still comes off the URL when none is given — proven without
// touching the network: a URL naming a repo that already exists here is
// refused by the mkdir claim before git ever runs.
for (const url of ['https://github.com/owner/alpha', 'git@github.com:owner/alpha.git'])
  ok(await post({ mode: 'clone', url }) === 400, `derived name collides, refused: ${url}`);
// ...and a name that IS given wins, which is what makes two checkouts of one
// repository possible. Same proof: it collides where the derived name would not.
ok(await post({ mode: 'clone', url: 'https://github.com/owner/somethingelse',
                name: 'alpha' }) === 400,
   'a supplied name is used instead of the repository\'s own');
// A supplied name goes through the same sanitizing an init's does, rather
// than being trusted because a URL was alongside it. Proven by collision
// again: each of these sanitizes to `alpha`, which already exists, so the
// mkdir claim refuses it before git runs — and a name that had NOT been
// sanitized would not have collided.
for (const name of ['../alpha', 'alpha/', 'alpha ', '.alpha', '_alpha'])
  ok(await post({ mode: 'clone', url: 'https://github.com/owner/repo', name }) === 400,
     `clone name sanitized to an existing one, refused: ${name}`);
// Every one of these sanitizes to `alpha`, which exists — so the refusal
// proves the transformation rather than a rejection, and nothing is created.
for (const name of ['../alpha', 'alpha!', '.alpha', '_alpha', 'alpha '])
  ok(await post({ name, mode: 'init' }) === 400,
     `init name sanitized to an existing one, refused: ${name}`);
// ...and the one thing that is still refused outright: a name with nothing in
// it to name a directory after.
for (const name of ['', '   ', '---', '...', '/'])
  ok(await post({ name, mode: 'init' }) === 400,
     `name refused: ${name || '(empty)'}`);
// The positive case, and the only place the sanitized name is observable:
// a messy one is accepted and the directory is what GitHub would have made.
const made = await postJson({ name: 'My New App!', mode: 'init' });
ok(made.status === 200 && made.body.name === 'My-New-App',
   'a name with spaces and punctuation is created as GitHub would spell it');
ok(existsSync(`${DIR}/ws/My-New-App/.git`),
   '...and that is the directory on disk');
ok(await post({ name: 'q2', mode: 'sideways' }) === 400, 'unknown mode refused');

// ---- a name already taken ----------------------------------------------
// Said in the dialog rather than only by the server, because the server can
// only answer after Create — and the case that needs it most is the one with
// the field left EMPTY, where the name comes from the repository and is never
// typed at all.
await page.click('#bNewProj');
await page.waitForSelector('#pmodal:not([hidden])');
await page.click('#pClone');
await page.fill('#pUrl', 'https://github.com/owner/alpha.git');
await page.fill('#pName', '');
ok(await page.$eval('#pName', el => el.classList.contains('bad'))
   && await page.$eval('#pNamePreview', el => !el.hidden && /already exists/.test(el.textContent)),
   'an empty name whose repository collides is marked red in the dialog');
await page.fill('#pName', 'alpha-two');
ok(await page.$eval('#pName', el => !el.classList.contains('bad')),
   '...and clears the moment the name is free');
await page.fill('#pName', 'beta');
ok(await page.$eval('#pName', el => el.classList.contains('bad')),
   '...a typed name that is taken is marked too');
await page.keyboard.press('Escape');

// ---- push rights -------------------------------------------------------
// Off by default, and the box only exists where pushing could mean anything.
await page.click('#bNewProj');
await page.waitForSelector('#pmodal:not([hidden])');
ok(await page.$eval('#pPushField', el => el.hidden),
   'a local repo is not asked about push rights');
await page.click('#pClone');
ok(await page.$eval('#pPushField', el => !el.hidden)
   && await page.$eval('#pPush', el => !el.checked),
   'cloning is, and read-only is the default');
await page.keyboard.press('Escape');

// A public clone cannot push, and is told so rather than being given rights
// that would fail at the first attempt.
ok(await post({ mode: 'clone', url: 'https://github.com/owner/pushless',
                push: true }) === 400,
   'asking to push with neither a token nor a key is refused');

// One project per repository. Driven at the module, because claiming the
// second would otherwise need two real clones.
const rights = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('p', ${
  JSON.stringify(new globalThis.URL('../projects.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
saved = {}
m.configure(run=lambda *a, **k: {'code': 0, 'out': ''}, workspace='/tmp',
            agent_keys=lambda: [], gh_authed=lambda: False,
            ensure_deploy_alias=lambda *a: '', repo_path=lambda u: u,
            build_claude_md=lambda *a, **k: '', project_name=None,
            github_url=None, state=d, home=d,
            write_json=lambda p, o: open(p, 'w').write(json.dumps(o)))
out = {}
# The remote's identity, however it is spelled — a deploy-key alias hides the
# host but the path is still owner/repo, and case does not distinguish repos.
out['ssh_alias'] = m.repo_of_remotes('origin\tgit@bb-thing:Owner/Repo.git (fetch)')
out['https'] = m.repo_of_remotes('origin\thttps://github.com/owner/repo (push)')
out['not_a_repo'] = m.repo_of_remotes('origin\tgit@host:one/two/three.git (fetch)')
m.grant_push('first', 'owner/repo', 'key')
out['holder'] = m.push_holder('owner/repo')
out['free'] = m.push_holder('owner/other')
out['may'] = [m.may_push('first'), m.may_push('second')]
m.drop_push('first')
out['after_drop'] = m.push_holder('owner/repo')
print(json.dumps(out))
`], { encoding: 'utf8' });
const rj = JSON.parse(rights.trim().split('\n').pop());
ok(rj.ssh_alias === 'owner/repo' && rj.https === 'owner/repo',
   'a deploy-key alias and an https remote name the same repository');
ok(rj.not_a_repo === '',
   '...and something that is not an owner/repo path is not guessed at');
ok(rj.holder === 'first' && rj.free === '',
   'a granted repository names its holder, and an ungranted one names nobody');
ok(rj.may[0] === true && rj.may[1] === false, 'only the granted project may push');
ok(rj.after_drop === '',
   'deleting the project is what frees the repository for another');

// ---- a token that belongs to one project -------------------------------
// The dialog offers it only where it means something.
await page.click('#bNewProj');
await page.waitForSelector('#pmodal:not([hidden])');
ok(await page.$eval('#pTokenField', el => el.hidden),
   'a local repo is not asked for an access token');
await page.click('#pClone');
ok(await page.$eval('#pTokenField', el => !el.hidden)
   && await page.$eval('#pToken', el => el.type === 'password'),
   'cloning is, and it is not typed in the clear');
await page.click('#pmodalClose').catch(() => page.keyboard.press('Escape'));

// Shape is checked before it is written: the store is a one-line format, so a
// token with a space or a newline in it would produce a file git reads as
// something else.
for (const token of ['has space', 'two\nlines', 'sh', '#{}!'])
  ok(await post({ mode: 'clone', url: 'https://github.com/owner/tok', token }) === 400,
     `a token that is not one is refused: ${JSON.stringify(token)}`);

// The store itself, at the module: a real clone would need GitHub on the other
// end, and this is the half that decides whether the token stays this
// project's alone.
const tok = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('p', ${
  JSON.stringify(new globalThis.URL('../projects.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
m.configure(run=lambda *a, **k: {'code': 0, 'out': ''}, workspace='/tmp',
            agent_keys=lambda: [], gh_authed=lambda: False,
            ensure_deploy_alias=lambda *a: '', repo_path=lambda u: u,
            build_claude_md=lambda *a, **k: '', project_name=None,
            github_url=None, state=d, home=d, write_json=lambda *a: None)
helper = m.write_token('alpha', 'ghp_ExampleTokenValue123')
f = os.path.join(d, 'gitcreds', 'alpha')
out = {'helper': helper,
       'line': open(f).read().strip(),
       'mode': oct(os.stat(f).st_mode & 0o777),
       'dirmode': oct(os.stat(os.path.dirname(f)).st_mode & 0o777),
       'lookup': m.token_helper('alpha'),
       'other': m.token_helper('beta')}
m.forget_token('alpha')
out['gone'] = not os.path.exists(f)
print(json.dumps(out))
`], { encoding: 'utf8' });
const tj = JSON.parse(tok.trim().split('\n').pop());
ok(tj.line === 'https://x-access-token:ghp_ExampleTokenValue123@github.com',
   'a token is stored in git\'s own credential-store format');
ok(tj.mode === '0o600' && tj.dirmode === '0o700',
   '...readable only by the user that runs git, in a directory to match');
ok(tj.helper.startsWith('store --file=') && tj.helper.endsWith('/gitcreds/alpha'),
   '...and the helper git is given names that one file');
ok(tj.lookup === tj.helper && tj.other === '',
   'a project with no token gets no helper — it is not shared, it is absent');
ok(tj.gone, 'and forgetting one removes it');

// ---- which credential the remote actually uses -------------------------
// At the module for the same reason as the store above: the interesting half
// is what gets written into `git remote set-url`, and a real remote would put
// GitHub on the other end of a unit test. `run` is stubbed to answer the one
// question set_auth asks and to record the one command it issues.
const authOut = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('p', ${
  JSON.stringify(new globalThis.URL('../projects.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
state = {'url': 'git@bb-depkey:Owner/Repo.git'}
issued = []
state['helper'] = ''
def fake_run(cmd, **k):
    if cmd[3:5] == ['remote', 'get-url']:
        return {'code': 0, 'out': state['url'], 'err': ''}
    if cmd[3:5] == ['remote', 'set-url']:
        issued.append(cmd[-1]); state['url'] = cmd[-1]
        return {'code': 0, 'out': '', 'err': ''}
    # The credential helper, remembered: whether the repo is pointed at its own
    # token is what tells "access token" from "disabled", so a stub that always
    # answered empty would make every https remote read as disabled.
    if cmd[3:6] == ['config', '--local', '--replace-all']:
        state['helper'] = ''
        return {'code': 0, 'out': '', 'err': ''}
    if cmd[3:6] == ['config', '--local', '--add']:
        state['helper'] = cmd[-1]
        return {'code': 0, 'out': '', 'err': ''}
    if cmd[3:6] == ['config', '--local', '--get-all']:
        return {'code': 0, 'out': state['helper'], 'err': ''}
    return {'code': 0, 'out': '', 'err': ''}
m.configure(run=fake_run, workspace='/tmp',
            agent_keys=lambda: [], gh_authed=lambda: False,
            ensure_deploy_alias=lambda *a: '', repo_path=lambda u: u,
            build_claude_md=lambda *a, **k: '', project_name=None,
            github_url=None, state=d, home=d,
            write_json=lambda p, v: open(p, 'w').write(json.dumps(v)))
out = {}
m.grant_push('alpha', 'owner/repo', 'key')
out['ssh_seen'] = m.remote_auth('/tmp/alpha')
# No token yet: the switch has to refuse rather than write a remote that
# cannot authenticate.
out['no_token'] = m.set_auth('alpha', '/tmp/alpha', 'https')[1]
out['bad_mode'] = m.set_auth('alpha', '/tmp/alpha', 'nonsense')[1]
m.write_token('alpha', 'ghp_ExampleTokenValue123')
out['opts_on_key'] = m.auth_options('alpha', '/tmp/alpha')
out['to_https'] = m.set_auth('alpha', '/tmp/alpha', 'https')
out['now_https'] = m.remote_auth('/tmp/alpha', 'alpha')
out['opts_on_token'] = m.auth_options('alpha', '/tmp/alpha')
out['token_kept'] = bool(m.token_helper('alpha'))
out['back'] = m.set_auth('alpha', '/tmp/alpha', 'ssh')
# ...and off altogether, which is its own answer rather than a broken second
# one: an https remote with the helper taken off it authenticates with nothing.
out['off'] = m.set_auth('alpha', '/tmp/alpha', 'none')
out['now_off'] = m.remote_auth('/tmp/alpha', 'alpha')
out['issued'] = issued
print(json.dumps(out))
`], { encoding: 'utf8' });
const aj = JSON.parse(authOut.trim().split('\n').pop());
ok(aj.ssh_seen === 'ssh',
   'a deploy-key alias is read as ssh, host and all — it is the URL form that decides');
ok(/no access token/.test(aj.no_token),
   'switching to a token nobody stored is refused, not written');
ok(aj.opts_on_key.now === 'ssh' && aj.opts_on_key.token && aj.opts_on_key.ssh,
   'with both credentials present the dialog is offered a real choice');
ok(aj.issued[0] === 'https://github.com/Owner/Repo.git',
   'switching to the token rewrites origin to https, with the repository still spelled the way it is spelled');
ok(aj.now_https === 'https' && aj.token_kept,
   '...and the token file it now uses is still the project\'s own');
ok(aj.opts_on_token.ssh,
   '...with the deploy key still offered, because the ssh URL was remembered');
ok(aj.issued[1] === 'git@bb-depkey:Owner/Repo.git',
   'switching back restores the exact alias, which nothing could have guessed');
ok(/not an authentication mode/.test(aj.bad_mode),
   'a mode nobody offers is refused rather than written');
ok(!aj.off[1] && /nothing/.test(aj.off[0]) && aj.now_off === 'none',
   'and Disabled is a third answer: https with no token, authenticating with nothing');

// ---- deploy keys -------------------------------------------------------
// The harness agent holds one throwaway key. The endpoint lists its public
// half; the dialog offers it; picking it for a clone writes the .pub selector
// and the per-repo alias into the scratch home. The clone itself then fails —
// the alias resolves against the real HOME's ssh config, which has never
// heard of it — which is exactly what makes this test offline-safe: the
// container-side writes all happen before git runs.
const keys = await page.evaluate(async () =>
  (await (await fetch('/api/pubkeys')).json()).keys);
ok(keys.length === 1 && keys[0].name === 'github_testkey'
   && keys[0].pub.startsWith('ssh-ed25519 '),
   'the agent key is listed with its public half');

await page.click('#bNewProj');
await page.click('#pClone');
await page.waitForFunction(() => !document.getElementById('pKeyField').hidden);
ok(await page.$eval('#pPubWrap', el => el.hidden), 'no key picked, no key shown');
await page.selectOption('#pKey', 'github_testkey');
ok(await page.$eval('#pPub', el => el.value.startsWith('ssh-ed25519 ')),
   'picking the key shows its public half to copy to GitHub');

await page.fill('#pUrl', 'https://github.com/owner/kproj');
await page.click('#pCreate');
// A clone is a background job now: the dialog gets out of the way as soon as
// the job is accepted, and the Projects card carries it from there — which is
// also what happens when the page is closed a second later.
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 20000 });
ok(true, 'the dialog closes once the clone is accepted, rather than holding the request');
// The row arrives with the poll that follows the accept, not with the close:
// asserted after waiting for it, since a loaded box can put a frame between
// the two — this read as a missing row on the first run that got here with
// the earlier files no longer crashing out.
await page.waitForSelector('#projects .row.job .name', { timeout: 20000 });
ok(await page.$eval('#projects .row.job .name', el => el.textContent === 'kproj'),
   'the Projects card shows the job where its result will appear');
ok(await page.$eval('#projects .row.job .sub', el => /clon|start/.test(el.textContent))
   && await page.$('#projects .row.job .dots') !== null,
   '...saying what it is doing, with an ellipsis rather than a parsed percentage');
ok(await page.$eval('#bNewProj', b => b.disabled),
   '...and New project is dead while it runs — one job at a time');
// The failure lands on the card, not in a toast that is gone in seven
// seconds: the page may not have been open when it happened.
await page.waitForFunction(() => {
  const s = document.querySelector('#projects .row .sub.bad');
  return s && s.textContent.length > 0;
}, { timeout: 60000 });
ok(await page.$('#projects .row.job') === null
   && await page.$eval('#bNewProj', b => !b.disabled),
   'the job ends and the controls come back');
ok(!existsSync(`${DIR}/ws/kproj`), '...and a failed clone leaves no directory');
ok(await page.$('#bJobOk') !== null, 'the failure stays until it is dismissed');
await page.click('#bJobOk');
await page.waitForFunction(() => !document.querySelector('#projects .row .sub.bad'));
ok(true, '...and dismissing clears it');
await page.click('#bNewProj');
await page.click('#pClone');
await page.waitForFunction(() => !document.getElementById('pKeyField').hidden);
const pub = readFileSync(`${DIR}/home/.ssh/bb_github_testkey.pub`, 'utf8');
ok(pub.trim() === keys[0].pub, 'the .pub selector was written from the agent, not the request');
const cfg = readFileSync(`${DIR}/home/.ssh/config`, 'utf8');
ok(cfg.includes('Host bb-github_testkey') && cfg.includes('IdentitiesOnly yes')
   && cfg.includes(`${DIR}/home/.ssh/bb_github_testkey.pub`),
   'the per-repo alias names the .pub and pins IdentitiesOnly');
ok(await post({ mode: 'clone', url: 'https://github.com/owner/kproj',
                key: 'no_such_key' }) === 400, 'an unknown key name is refused');
await page.click('#pCancel');

// ---- a job outlives the page, and can be stopped ------------------------
// The whole reason a clone stopped being an HTTP request. The harness's git
// stalls on this URL, so there is something still running to look at.
await page.click('#bNewProj');
await page.click('#pClone');
await page.fill('#pUrl', 'https://github.com/owner/slowclone');
await page.click('#pCreate');
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 20000 });
await page.waitForFunction(() =>
  document.querySelector('#projects .row.job .name')?.textContent === 'slowclone');
ok(existsSync(`${DIR}/ws/slowclone`),
   'the directory is claimed up front, so a second request cannot take the name');
ok(await page.$$eval('#projects .row .name',
     ns => ns.filter(n => n.textContent === 'slowclone').length === 1),
   '...and the half-made directory is not also listed as a broken project');

await page.reload();
await ready(page);
ok(await page.$eval('#projects .row.job .name', el => el.textContent === 'slowclone'),
   'a reload finds the job still running — it belongs to the server, not the page');
await page.waitForFunction(() => {
  const s = document.querySelector('#projects .row.job .sub');
  return s && /\d+s/.test(s.textContent);
}, { timeout: 15000 });
ok(true, '...and says how long it has been going');

await page.click('#bJobStop');
await page.waitForFunction(() => !document.querySelector('#projects .row.job'),
                           { timeout: 30000 });
ok(!existsSync(`${DIR}/ws/slowclone`),
   'Abort stops it and removes the half-cloned directory');
ok((await page.$eval('#projects .row .sub.bad', el => el.textContent)).includes('stopped'),
   '...and says so rather than looking like a failure of its own');
await page.click('#bJobOk');
await page.waitForFunction(() => !document.querySelector('#projects .row .sub.bad'));

// ---- link to GitHub ----------------------------------------------------
// alpha has a remote, beta does not: the chain button shows on exactly the
// unlinked one. The dialog is the clone form's third mode — URL and key only.
// With the stub gh (never authenticated) a key is mandatory, and the attempt
// stops at the unresolvable bb- alias, before any remote is added — the
// success path needs a live GitHub and stays a manual test, like the clone's.
ok(await page.$('#projects [data-l="beta"]') !== null
   && await page.$('#projects [data-l="alpha"]') === null,
   'the link button shows only on a repo with no remote');
await page.click('#projects [data-l="beta"]');
ok(await page.$eval('#pTitle', el => el.textContent === 'Link beta to GitHub'),
   'the dialog names the project it is linking');
// The deploy-key pick from the clone flow above must not ride along into
// this open — the select starts empty and repopulates from a fresh fetch.
await page.waitForFunction(() => document.querySelectorAll('#pKey option').length > 1);
ok(await page.$eval('#pKey', el => el.value === ''),
   'a new open starts with no key selected, whatever the last one picked');
ok(await page.$eval('#pSrcField', el => el.hidden)
   && await page.$eval('#pNameField', el => el.hidden)
   && await page.$eval('#pAboutField', el => el.hidden)
   && await page.$eval('#pUrlField', el => !el.hidden),
   'link mode asks for the URL and key only');
await page.fill('#pUrl', 'git@github.com:owner/beta-remote.git');
await page.click('#pCreate');
ok(await page.$eval('#pErr', el => el.textContent.includes('deploy key')),
   'no PAT and no key picked is refused before the round-trip');
await page.waitForFunction(() => !document.getElementById('pKeyField').hidden);
await page.selectOption('#pKey', 'github_testkey');
await page.click('#pCreate');
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 20000 });
await page.waitForFunction(() => {
  const s = document.querySelector('#projects .row .sub.bad');
  return s && s.textContent.length > 0;
}, { timeout: 60000 });
ok(true, 'a link runs as a job too, and its failure lands on the card');
ok(!readFileSync(`${DIR}/ws/beta/.git/config`, 'utf8').includes('[remote'),
   '...and no remote was added — the check comes before the configuration');
await page.click('#bJobOk');
ok(await post({ name: 'alpha', url: 'https://github.com/owner/alpha',
                key: 'github_testkey' }, '/api/link') === 400,
   'a repo that already has a remote is refused');
ok(await post({ name: 'oldproj', url: 'https://github.com/owner/oldproj',
                key: 'github_testkey' }, '/api/link') === 400,
   'a directory that is not a git repository is refused');
ok(await post({ name: 'nosuch', url: 'https://github.com/owner/x',
                key: 'github_testkey' }, '/api/link') === 400,
   'an unknown project is refused');
ok(await post({ name: 'beta', url: 'https://github.com/owner/beta' },
              '/api/link') === 400,
   'no PAT and no key is refused server-side too');

// The refusals above are answered with 400s on purpose — and the deploy-key
// clone is made to fail with a 500 — and the browser logs each as a failed
// resource. Those lines are the tests passing, not a fault. Anything else is
// still a failure.
// ---- the bin -------------------------------------------------------------
// Deleting a project moves it to /workspace/.trash and every word on the page
// says so. This is the other half of that promise: seeing what is in there,
// putting one back, and — the only irreversible control on the page —
// destroying one.
mkdirSync(`${DIR}/ws/.trash/oldproj`, { recursive: true });
writeFileSync(`${DIR}/ws/.trash/oldproj/keep.txt`, 'still here\n');
// It has to be visible before it can be pressed. Keyed to `.eye` alone, the
// icon rule missed this button (an `.ic`) and its SVG got the browser
// default — fill:black, stroke:none — which draws nothing at all, because
// every path in it is an open stroke.
const binInk = await page.$eval('#bTrash svg', e => {
  const c = getComputedStyle(e);
  return { stroke: c.stroke, fill: c.fill, w: e.getBoundingClientRect().width };
});
ok(binInk.stroke !== 'none' && binInk.fill === 'none' && binInk.w >= 12,
   `the bin button's icon is actually drawn (stroke ${binInk.stroke}, fill ${binInk.fill}, ${binInk.w}px)`);
await page.click('#bTrash');
await page.waitForSelector('#tmodal:not([hidden])', { timeout: 10000 });
await page.waitForFunction(() => document.querySelector('#tList .trow'),
                           { timeout: 10000 });
ok(await page.$eval('#tList .trow', r => r.dataset.t) === 'oldproj',
   'the bin lists what was deleted, which nothing else on the page could show');

// Put back: a move, and the files come with it.
await page.click('#tList .trow[data-t="oldproj"] [data-trestore]');
await page.waitForFunction(() => !document.querySelector('#tList .trow[data-t="oldproj"]'),
                           { timeout: 10000 });
ok(existsSync(`${DIR}/ws/oldproj/keep.txt`) && !existsSync(`${DIR}/ws/.trash/oldproj`),
   '...and Put back is a move, so the files arrive with the name');

// Destroying one asks for the name to be typed. A click is not enough for the
// one control here with nothing behind it.
rmSync(`${DIR}/ws/oldproj`, { recursive: true, force: true });
mkdirSync(`${DIR}/ws/.trash/oldproj`, { recursive: true });
writeFileSync(`${DIR}/ws/.trash/oldproj/keep.txt`, 'still here\n');
await page.evaluate(() => drawTrash());
await page.waitForFunction(() => document.querySelector('#tList .trow[data-t="oldproj"]'),
                           { timeout: 10000 });
await page.click('#tList .trow[data-t="oldproj"] [data-tpurge]');
await page.waitForSelector('#tList .dropbox input', { timeout: 10000 });
ok(await page.$eval('#tList .dropbox .danger', b => b.disabled),
   'Delete for good is dead until the name is typed back');
await page.fill('#tList .dropbox input', 'gamm');
ok(await page.$eval('#tList .dropbox .danger', b => b.disabled),
   '...and stays dead for a near miss');
await page.fill('#tList .dropbox input', 'oldproj');
ok(!await page.$eval('#tList .dropbox .danger', b => b.disabled),
   '...and wakes on the name itself');
await page.click('#tList .dropbox .danger');
await page.waitForFunction(() => !document.querySelector('#tList .trow[data-t="oldproj"]'),
                           { timeout: 10000 });
ok(!existsSync(`${DIR}/ws/.trash/oldproj`),
   'and then it is gone, files and all — the one thing here with nothing after it');
await page.click('#tClose');
await page.waitForFunction(() => document.getElementById('tmodal').hidden);

const errs = page.errors.filter(e => !/status of (400|500)/.test(e));
ok(errs.length === 0, `zero console errors${errs.length ? ' — ' + errs.join(' | ') : ''}`);
await done(browser);
