// A page waiting on its data waits as itself (R218 step 16): its template is
// laid out the way the page lands. Nothing held that, so a page whose layout
// moved kept the template of the one before it (the operator, 17 Oct: Users
// waited as a table after it became a list beside a detail). Each page and
// notebook view here is drawn loaded, then put back to its template with its
// reads held, and the two outlines compared: the bar, the tiles, the status
// line, a list beside a detail and where its detail starts, a table, and the
// edges of the first floating card. At a desk and on a phone.
import { launch, newPage, ok, done, ready, sleep, URL } from './lib.mjs';

const PAGES = [
  ['home', '#/home', 'homeData = null; homeFetching = true; renderHomeInto(0)'],
  ['jobs', '#/jobs', 'jobsList = null; renderJobsInto(0)'],
  ['nodes', '#/machines/nodes', 'nodesList = null; renderNodesInto(0)'],
  ['storage', '#/machines/storage', 'storageList = null; renderStorageInto(0)'],
  // Deploy is an undeployed node's alone, which is not known while it waits.
  // ...and its four sections are a deployed node's: the fixture's is not, so
  // the page draws one line and Deploy where the template, waiting for the
  // node a person mostly has, draws them.
  ['nginx', '#/containers/nginx', 'nginxList = null; renderNginxInto(0)',
   ['barSig', 'card', 'title:Hostnames', 'title:Routes', 'title:Certificates', 'title:Image']],
  // This machine is a node's with a GPU or Claude Code row to show, which
  // is not known while it waits; on a phone, where it is drawn it is the one
  // open section, so the list's table is folded under it.
  ['toolchains', '#/build/toolchains', 'toolchains = null; renderToolchainsInto(0)', ['title:This machine', 'phone:table']],
  // The fixture's node never reported its images (known false), so the page
  // lands with no tiles; a node that has carries them, as the template does.
  ['emulator', '#/build/emulator', 'emu = null; renderEmulatorInto(0)', ['tiles']],
  ['phone', '#/build/phone', 'ph = null; renderPhoneInto(0)'],
  ['runner', '#/build/runner', 'nodesList = null; renderRunnerInto(0)'],
  ['users', '#/people/users', 'usersList = null; renderUsersInto(0)'],
  ['roles', '#/people/roles', 'rolesData = null; renderRolesInto(0)'],
  ['profile', '#/settings/profile', 'profile = null; renderProfileInto(0)'],
  ['devices', '#/settings/devices', 'devApps = null; renderDevicesInto(0)'],
  ['notices', '#/notifications', 'noticesData = null; noticesFetching = true; renderNoticesInto(0)'],
  ['containers', '#/containers', 'dockerList = null; for (const k in dockerSeen) delete dockerSeen[k]; renderDockerInto(0)'],
  ['analysis', '#/projects/findings', 'findings = {loading: true}; renderFindingsInto(0)'],
];
// A notebook view's template is what a project not yet read shows: the view
// is drawn loaded on one project and waiting on another.
const VIEWS = ['briefing', 'roadmap', 'bugs', 'git', 'tests', 'analysis', 'design', 'artifacts', 'settings'];
// Sections a view draws only from what the project holds: a red CI, a
// README, a Brief to keep.
// A phone opens one section of a view at a time, so the Git view's
// Branches table is folded under Changes on the page and not in its wait.
const VIEW_SKIP = { git: ['title:CI', 'title:README.md', 'phone:table'], briefing: ['title:Brief'] };
const HELD = /\/api\/(?!status|layout|revs|presence)/;

// The outline of what is on show in `sel`: a template's wrapper (.skt) is
// looked through, its "loading…" word for a screen reader is not counted.
const outline = sel => {
  // on screen: a page left at a desk stays in the pane, hidden by its
  // visibility with its box kept, so a box alone is not on show
  const shown = e => !!e && e.checkVisibility({ visibilityProperty: true, opacityProperty: true });
  // the one on screen: a page or notebook drawn before stays in the DOM
  const root = [...document.querySelectorAll(sel)].find(shown);
  if (!root) return null;
  const first = q => [...root.querySelectorAll(q)].find(shown) || null;
  const box = e => { const r = e.getBoundingClientRect(); return { l: Math.round(r.left), r: Math.round(r.right) }; };
  // the page's own bar band, wherever its markup keeps it
  const bar = root.querySelector('.docbarrow, .histbar.docbarrow');
  // The first floating card: a bordered block at least half the list wide.
  const wide = root.getBoundingClientRect().width / 2;
  const card = [...root.querySelectorAll('*')].find(e => {
    if (!shown(e) || e.getBoundingClientRect().width < wide || e.closest('.tiles, .tile')) return false;
    const c = getComputedStyle(e);
    return parseFloat(c.borderLeftWidth) > 0 && parseFloat(c.borderRightWidth) > 0 && c.borderLeftStyle !== 'none'
      && !/^(BUTTON|INPUT|SELECT|TEXTAREA|SPAN|A|CODE|I|PRE)$/.test(e.tagName);   // a diff or a command is content, not a card
  });
  const split = first('.rsplit, .ssplit');
  const detail = split && [...split.children].find(e => shown(e) && !e.matches('.rlist, .snav'));
  return {
    // a template drawn at all: its shimmering shapes on show, or a
    // template's frame holding only what is known before the read (Profile's
    // list of sections on a phone); waiting with none is a view that draws
    // at once from what the page already holds
    skel: !!first('.skel .skv, .skel .sk-b, .skel .sk-row, .skt > :not(.sk-said)'),
    waiting: !!first('.loading'),
    // the page empty here: a line saying so and nothing laid out under it
    // (a notebook view's empty hint, a page's one line of hint alone)
    empty: !!first('.empty, .nbempty, .doclist > .hint:only-child') && !first('.tbl') && !first('.rrow, .row, .tc, .card'),
    // where the first card starts under the bar, the tiles and the status line
    top: card ? Math.round(card.getBoundingClientRect().top - root.getBoundingClientRect().top) : null,
    bar: !!bar && shown(bar),
    tiles: !!first('.tiles'),
    status: !!first('.headline'),
    split: !!split,
    detailX: detail ? box(detail).l : null,
    table: !!first('.tbl'),
    card: card ? box(card) : null,
    // a part still on its way, saying so (its dots): not landed yet
    busy: !!first('.dots'),
    // What the page is made of, not only whether it has a bar (R218, the
    // operator 18 Oct: Containers and Nodes waited as pages they had
    // stopped being): the bar's parts in order (its picker with its word or
    // without, a search, Cards and List, its buttons), the jump bar, and
    // the titles of the sections on show.
    barSig: bar ? [...bar.children].filter(shown).map(e => e.matches('label.pick') ? (e.querySelector('.pickw') ? 'picker' : 'picker without its word')
      : e.matches('input') ? 'search' : e.matches('.pseg') ? 'a switch' : e.matches('.actbar') ? 'buttons' : null).filter(Boolean).join(', ') : '',
    jump: !!first('.sectjump'),
    titles: [...root.querySelectorAll('details.sect > summary .t')].filter(shown).map(e => e.textContent.trim()).filter(Boolean),
  };
};

// What differs between the page and its template, in words; "" for nothing.
const differ = (got, tpl, skip = []) => {
  if (!got || !tpl) return `${got ? 'no template' : 'no page'} to measure`;
  if (!tpl.skel) return tpl.waiting ? 'it waits with words, not a template' : '';   // draws at once: nothing to hold
  const out = [];
  if (!skip.includes('barSig') && got.barSig !== tpl.barSig) out.push(`its bar is ${got.barSig || 'empty'} on the page, ${tpl.barSig || 'empty'} in the template`);
  if (!skip.includes('jump') && got.jump !== tpl.jump) out.push(`jump bar: page ${got.jump ? 'has' : 'has none'}, template ${tpl.jump ? 'has' : 'has none'}`);
  // A title the template promises is one the page draws; a section the page
  // only sometimes has (a node's GPU, a managed node's Storage) is named in
  // the page's skip list as `title:NAME`.
  const spare = skip.filter(k => k.startsWith('title:')).map(k => k.slice(6));
  const lost = tpl.titles.filter(t => !got.titles.includes(t) && !spare.includes(t));
  const extra = got.titles.filter(t => !tpl.titles.includes(t) && !spare.includes(t));
  if (lost.length) out.push(`the template has sections the page does not: ${lost.join(', ')}`);
  if (extra.length) out.push(`the page has sections the template does not: ${extra.join(', ')}`);
  // An empty page has only its frame to compare: what fills it differs.
  for (const k of got.empty ? ['bar', 'tiles', 'status'] : ['bar', 'tiles', 'status', 'split', 'table'])
    if (!skip.includes(k) && got[k] !== tpl[k]) out.push(`${k}: page ${got[k] ? 'has' : 'has none'}, template ${tpl[k] ? 'has' : 'has none'}`);
  if (got.split && tpl.split && got.detailX !== null && tpl.detailX !== null && Math.abs(got.detailX - tpl.detailX) > 2)
    out.push(`the detail starts at ${got.detailX} on the page, ${tpl.detailX} in the template`);
  if (got.empty) return out.join('; ');
  if (!skip.includes('card') && !!got.card !== !!tpl.card) out.push(`card: page ${got.card ? 'floats one' : 'floats none'}, template ${tpl.card ? 'floats one' : 'floats none'}`);
  else if (got.card && (Math.abs(got.card.l - tpl.card.l) > 2 || Math.abs(got.card.r - tpl.card.r) > 2))
    out.push(`card edges ${got.card.l} to ${got.card.r} on the page, ${tpl.card.l} to ${tpl.card.r} in the template`);
  else if (got.card && !skip.includes('tiles') && Math.abs(got.top - tpl.top) > 24)
    out.push(`the first card starts ${got.top}px down on the page, ${tpl.top}px in the template`);
  return out.join('; ');
};

// A placeholder bar keeps the inset of what it stands for (B864: Home's
// Last jobs had its bars on its card's edge): none within 6px of the edged
// box it waits in.
const onTheWall = sel => {
  const shown = e => !!e && e.checkVisibility({ visibilityProperty: true, opacityProperty: true });
  const root = [...document.querySelectorAll(sel)].find(shown);
  if (!root) return '';
  const out = new Set();
  for (const bar of root.querySelectorAll('.skel .sk-b, .skel .skv')){
    const r = bar.getBoundingClientRect();
    if (!r.width || !shown(bar)) continue;
    let box = bar.parentElement;
    for (; box && box !== root; box = box.parentElement){
      const c = getComputedStyle(box);
      if (parseFloat(c.borderLeftWidth) > 0 && c.borderLeftStyle !== 'none') break;
    }
    if (!box || box === root) continue;
    const gap = r.left - box.getBoundingClientRect().left;
    if (gap < 6) out.add(`${box.className.split(' ').slice(0, 2).join('.')} ${Math.round(gap)}px`);
  }
  return [...out].join(', ');
};

// The page as it lands: a page reads more than once (the Emulator's list of
// images to add comes after its node's, its dots running meanwhile), so its
// outline is taken when nothing says it is on its way and two reads 400ms
// apart agree, for up to ten seconds.
const settled = async (page, sel) => {
  let was = await page.evaluate(outline, sel);
  for (let i = 0; i < 25; i++){
    await sleep(400);
    const now = await page.evaluate(outline, sel);
    if (!now?.busy && JSON.stringify(now) === JSON.stringify(was)) return now;
    was = now;
  }
  return was;
};

const browser = await launch();
for (const [W, H] of [[1280, 1000], [393, 852]]){
  const page = await newPage(browser, W < 900 ? { viewport: { width: W, height: H }, isMobile: true, hasTouch: true }
                                              : { viewport: { width: W, height: H } });
  await page.goto(URL);
  await ready(page);
  const where = W < 900 ? 'on a phone' : 'at a desk';
  for (const [name, hash, reset, skip] of PAGES){
    await page.evaluate(h => { location.hash = h; }, hash);
    await page.waitForFunction(() => { const l = [...document.querySelectorAll('.pane .doc.on')].find(e => e.checkVisibility({ visibilityProperty: true, opacityProperty: true }));
      return l && l.children.length && !l.querySelector('.loading'); }, null, { timeout: 15000 }).catch(() => {});
    const got = await settled(page, '.pane .doc.on');
    await page.route(HELD, () => {});
    const err = await page.evaluate(js => { try { (0, eval)(js); return ''; } catch (e){ return String(e); } }, reset);
    await sleep(300);
    const tpl = await page.evaluate(outline, '.pane .doc.on');
    const wall = await page.evaluate(onTheWall, '.pane .doc.on');
    await page.unroute(HELD);
    ok(!wall, `${name}'s placeholder bars keep their card's inset ${where}${wall ? `: ${wall}` : ''}`);
    // A `phone:KEY` skips KEY at phone width alone.
    const skips = (skip || []).flatMap(k => k.startsWith('phone:') ? (W < 900 ? [k.slice(6)] : []) : [k]);
    const why = err || differ(got, tpl, skips);
    ok(!why, `${name} waits as itself ${where}${why ? `: ${why}` : ''}`);
  }
  const [shown, waiting] = W < 900 ? ['beta', 'delta'] : ['beta', 'gamma'];
  for (const v of VIEWS){
    await page.evaluate(([p, v]) => openNotebook(p, v), [shown, v]);
    await page.waitForFunction(() => { const n = [...document.querySelectorAll('.nb .nbview:not([hidden])')].find(e => e.checkVisibility({ visibilityProperty: true, opacityProperty: true }));
      return n && !n.querySelector('.loading'); }, null, { timeout: 15000 }).catch(() => {});
    const got = await settled(page, '.nb .nbview:not([hidden])');
    await page.route(HELD, () => {});
    await page.evaluate(([p, v]) => openNotebook(p, v), [waiting, v]);
    await sleep(600);
    const tpl = await page.evaluate(outline, '.nb .nbview:not([hidden])');
    const wall = await page.evaluate(onTheWall, '.nb .nbview:not([hidden])');
    await page.unroute(HELD);
    ok(!wall, `the notebook's ${v} view's placeholder bars keep their card's inset ${where}${wall ? `: ${wall}` : ''}`);
    const why = differ(got, tpl, (VIEW_SKIP[v] || []).flatMap(k => k.startsWith('phone:') ? (W < 900 ? [k.slice(6)] : []) : [k]));
    ok(!why, `the notebook's ${v} view waits as itself ${where}${why ? `: ${why}` : ''}`);
  }
  // A reload on a view draws that view's own template before anything is
  // read, as a press does (B865: five plain rows, then the view's head).
  for (const v of ['roadmap', 'bugs', 'tests', 'wiki']){
    await page.route(HELD, () => {});
    await page.route(/\/api\/status/, () => {});
    // Read as the page's own script finishes, before the first read could
    // replace it; a hash alone is the same document, so it is reloaded.
    await page.addInitScript(() => document.addEventListener('DOMContentLoaded', () => {
      const b = document.querySelector('.skboot .nbview');
      window.__boot = b ? { view: b.dataset.view || '', head: !!b.querySelector('.nbhead'), ids: b.querySelectorAll('[id]').length } : null;
    }));
    await page.goto('about:blank');
    await page.goto(`${URL}#/projects/beta/${v}`);
    await sleep(300);
    const boot = await page.evaluate(() => window.__boot);
    await page.unroute(HELD); await page.unroute(/\/api\/status/);
    ok(boot?.view === v && boot.head && boot.ids === 0,
       `a reload on the ${v} view draws its own template first, without the notebook's ids ${where} (${JSON.stringify(boot)})`);
    await page.goto(URL);
    await ready(page);
  }
  await page.close();
}
await done(browser);
