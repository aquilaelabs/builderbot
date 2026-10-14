// The sidebar cards: one rule for every card, the whole header is the
// collapse control and the drag handle. Order and collapsed-state live on
// the server like the pins do, so the phone and the desktop agree about how
// one machine's dashboard is arranged; a phone's own folds stay on the phone.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load. The markup's order is read and the
// headers wired from index.html, under the sidebar cards header, and the
// phone's own fold set (localStorage) is read there too.

"use strict";

let cards = {order: [], closed: []};   // filled from the markup once it exists, in index.html

// On a phone every card starts folded (the projects card, the one that
// started open, went with R218 step 3).
const cardShut = key => cards.closed.includes(key)
  || (isPhone() && !phoneOpen.has(key));

let cardDrag = null, cardsChangedAt = 0;   // when the operator last touched
                                           // the arrangement here: a poll
                                           // issued before that carries a
                                           // stale copy and must not win

const cardEls = () => [...document.querySelectorAll(".side .card[data-card]")];

function applyCards(animate){
  const side = document.querySelector(".col.side");
  const play = animate ? flip(cardEls, el => el.dataset.card) : null;
  // Only when the order is actually wrong. appendChild moves a node: remove
  // then insert, and a node leaving the document takes the focus inside it
  // with it. Once every fifteen seconds that is a shrug; during a sign-in the
  // card polls every 1.2s, and it knocked the phone's keyboard down under the
  // thumb of whoever was pasting the code in.
  const here = cardEls().map(el => el.dataset.card);
  const want = cards.order.filter(k => here.includes(k));
  if (want.join() !== here.filter(k => cards.order.includes(k)).join())
    for (const key of cards.order){
      const el = side.querySelector(`.card[data-card="${key}"]`);
      if (el) side.appendChild(el);   // appendChild moves, so this re-sorts in place
    }
  // A card mid-fold is left to its animation's own finish handler: snapping
  // the class on under it would cut the tween short.
  cardEls().forEach(el => {
    if (!el.getAnimations().length)
      el.classList.toggle("closed", cardShut(el.dataset.card));
  });
  play?.();
}

// Take on the arrangement another browser saved: a card it folded folds
// here with the same tween, one it moved slides to its place. The very first
// poll is the page finding out how things are, not a change, and lands
// instantly: a fold-up of every closed card on load would be theatre.
let cardsSynced = false;

function adoptCards(next){
  const prev = cards;
  cards = next;
  const reorder = prev.order.join() !== cards.order.join();
  if (cardsSynced && !noMotion())
    cardEls().forEach(el => {
      const k = el.dataset.card, shut = cardShut(k);
      if (shut !== el.classList.contains("closed") && rendered(el)
          && !el.getAnimations().length)
        slideCard(el, shut);
    });
  applyCards(cardsSynced && reorder);
  cardsSynced = true;
}

async function saveCards(){
  cardsChangedAt = performance.now();
  try{
    const r = await postJSON("/api/cards", cards);
    const j = await r.json();
    if (j.error) notify(j.error, true);
    else { cards = j.cards; applyCards(); }
  }catch(e){ notify("could not save the card layout: " + e, true); }
}

function toggleCard(key){
  const el = document.querySelector(`.card[data-card="${key}"]`);
  // On a PHONE the fold is a view, not an arrangement: it is kept for the
  // page's life and never written, so opening Tools on a phone to press one
  // button does not reach across to the desktop the arrangement was made on.
  if (isPhone()){
    const shut = !el.classList.contains("closed");
    if (shut) phoneOpen.delete(key); else phoneOpen.add(key);
    keepPhoneOpen();
    slideCard(el, shut);
    return;
  }
  const closing = !cards.closed.includes(key);
  cards.closed = closing ? [...cards.closed, key] : cards.closed.filter(k => k !== key);
  slideCard(el, closing);
  saveCards();
}

// The same pointer-based drag as the tab strip, turned vertical: the number
// of *other* visible cards whose midline is above the pointer is exactly the
// insertion index. A hidden card (findings without /reports) offers nothing
// to aim at, so it is re-appended after the visible order: the bottom is
// where it surfaces if it ever appears.
// Rendered, as opposed to merely present: a hidden card (findings without
// /reports) and one a phone hides by stylesheet both offer nothing to aim at.
const rendered = el => el && !el.hidden && el.getClientRects().length > 0;

function cardDropIndex(y, fromKey){
  let idx = 0;
  cardEls().forEach(el => {
    if (el.dataset.card === fromKey || !rendered(el)) return;
    const r = el.getBoundingClientRect();
    if (y > r.top + r.height / 2) idx++;
  });
  return idx;
}

function startCardDrag(ev, key){
  if (ev.pointerType === "mouse" && ev.button !== 0) return;
  // Same touch rule as the tab strip: hold half a second to pick the card up
  // (it dims), and a finger that moves sooner was swiping, not dragging.
  cardDrag = {key, x0: ev.clientX, y0: ev.clientY, y: ev.clientY, moved: false,
              armed: ev.pointerType !== "touch"};
  if (!cardDrag.armed)
    cardDrag.timer = setTimeout(() => {
      if (!cardDrag) return;
      cardDrag.armed = cardDrag.moved = true;
      document.body.classList.add("dragging");
      document.querySelector(`.card[data-card="${key}"]`)?.classList.add("held");
      edgeScroll();
    }, HOLD_MS);
  window.addEventListener("pointermove", onCardDrag);
  window.addEventListener("pointerup", endCardDrag);
  window.addEventListener("pointercancel", endCardDrag);
}

function onCardDrag(ev){
  if (!cardDrag) return;
  cardDrag.y = ev.clientY;
  const far = Math.hypot(ev.clientX - cardDrag.x0, ev.clientY - cardDrag.y0) >= 6;
  if (!cardDrag.armed){
    if (far) endCardDrag();
    return;
  }
  if (!cardDrag.moved){
    // The same few pixels of slop as a tab drag: a click is not a drag.
    if (!far) return;
    cardDrag.moved = true;
    document.body.classList.add("dragging");
    edgeScroll();
  }
  ev.preventDefault();
  placeCard();
}

// The drop step for cards, per move, and per frame while the sidebar creeps
// under a pointer held at its edge (edgeScroll).
function placeCard(){
  const vis = cards.order.filter(k => k !== cardDrag.key
    && rendered(document.querySelector(`.card[data-card="${k}"]`)));
  vis.splice(cardDropIndex(cardDrag.y, cardDrag.key), 0, cardDrag.key);
  const next = [...vis, ...cards.order.filter(k => !vis.includes(k))];
  if (next.join() !== cards.order.join()){
    cards.order = next;
    applyCards(true);                   // the displaced cards slide, not jump
  }
}

function endCardDrag(){
  clearTimeout(cardDrag?.timer);
  window.removeEventListener("pointermove", onCardDrag);
  window.removeEventListener("pointerup", endCardDrag);
  window.removeEventListener("pointercancel", endCardDrag);
  document.body.classList.remove("dragging");
  document.querySelectorAll(".card.held").forEach(el => el.classList.remove("held"));
  const moved = cardDrag?.moved;
  cardDrag = null;
  if (!moved) return;
  swallowClick = true;                  // ...and the click ending a drag is not
  setTimeout(() => swallowClick = false, 0);   //    a request to collapse
  saveCards();
}

// ---- who has a session on a project ----
// Who else has a conversation open on this project. Not a refusal any more
// (roadmap #24): they each work in a tree of their own, so the row says who is
// here rather than taking the button away. What IS refused is a second session
// on one Anthropic account, and that refusal comes from the server when the
// terminal is opened, in its own words.
// Keyed by the tmux-safe name (claude_with comes off the session names),
// so a project with a dot in its name is looked up by that: by its own
// name its row said nobody was here while a session ran (29 Sep).
const withMe = p => (state?.claude_with || {})[tmuxName(p)] || (state?.claude_with || {})[p] || [];
// The others, for the places that are about somebody else being here.
const othersOn = p => withMe(p).filter(n => n !== state?.me);
// Who has a conversation open here, one line each with a dot in front:
// bright while that session is working on a prompt, dim while it waits (the
// operator, 24 Sep, in place of one sentence naming them all). BuilderBot
// account names, not the Anthropic logins behind them: whose session it is
// on this box is the question somebody looking at the row is asking. Your
// own is last and says so, so the other people, the part that is news, come
// first.
// The two maps behind those rows, fetched on their own when the revs token
// `live` moves: a session starting, ending or turning to work shows within
// a few seconds, where the status poll runs git for every project and
// stays at fifteen (the operator, 25 Sep).
async function liveRefresh(){
  let j;
  try{ j = await (await fetch("/api/live")).json(); }catch(e){ return; }
  if (!state || !j || j.error) return;
  state.claude_with = j.claude_with || {};
  state.claude_busy = j.claude_busy || {};
  state.claude_where = j.claude_where || {};
  drawProjects(state.projects);
}
function sessionRows(proj){
  const all = withMe(proj);
  if (!all.length) return "";
  const busy = new Set((state?.claude_busy || {})[proj] || []);
  const names = [...all].sort((a, b) => (a === state?.me) - (b === state?.me));
  // The session dot, the same one the session's tab, the phone's Terminal
  // tab and the Sessions card wear (stateDot's rule): working pulses in
  // the note color, waiting is the warn color. The row had a dot of its
  // own in other colors, and the same state read differently in each
  // place (the operator, 29 Sep).
  // One line per account per node, the node in brackets, so a person with
  // a session on two machines is two lines and each says whether it is
  // working there (the operator, 30 Sep). Where the payload has no node
  // rows (a session on this container), one line per account, as before.
  const where = (state?.claude_where || {})[tmuxName(proj)] || (state?.claude_where || {})[proj] || [];
  // ...and only while it names the same people as the map beside it, which
  // is the one a poll that has not carried it yet still fills.
  const whos = new Set(where.map(r => r.who));
  const agrees = where.length && names.every(n => whos.has(n)) && [...whos].every(w => names.includes(w));
  const rows = agrees
    ? [...where].sort((a, b) => (a.who === state?.me) - (b.who === state?.me) || a.node.localeCompare(b.node))
    : names.map(n => ({who: n, node: "", working: busy.has(n)}));
  // What changed since a session started that it does not see until it is
  // started again, said under it with what for (the operator, 12 Oct): a
  // toolchain put on its node's PATH, BuilderBot updated.
  return rows.map(r => `<div class="sessone"><span class="st ${r.working ? "working" : "waiting"}" title="${
    r.working ? "working on a prompt" : "waiting for a prompt"}"></span>${esc(r.who)}${
    r.who === state?.me ? " (you)" : ""}${r.node ? ` <span class="dim">(${esc(r.node)})</span>` : ""}</div>${
    (r.behind || []).length ? `<div class="sessbehind">Restart ${r.who === state?.me ? "your session" : "this session"} to use what changed: ${
      esc(r.behind.join("; "))}.</div>` : ""}`).join("");
}

// ---- sidebar cards ---------------------------------------------------

const keepPhoneOpen = () => { try{ localStorage.setItem("bb.phoneOpen", JSON.stringify([...phoneOpen])); }catch{} };
