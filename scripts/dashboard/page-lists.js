// Long lists, more as the reader gets there (the operator, 16 Oct: in place
// of Previous and Next): the first page of rows on screen, and the next one
// shown when the foot of the list comes into view, until all of it is. The
// foot says how much is on screen of the whole, "50 of 80 bugs", and keeps a
// Show more for a keyboard or a reader who would rather press; with all of
// it shown there is no foot. The order still means something (bugs by
// severity, the roadmap in the order the work has to happen in), and nothing
// above the rows moves as more arrive under them.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

"use strict";

const PAGE = 25;

const pageState = {};      // list id -> how many pages of it are shown, from 1

// The notebook this list is in, folded into the key. A notebook is a CLONE
// of one template, so every id inside it is shared by every open notebook,
// and a key of "artList" was one bucket for all of them: a SHORT list in
// another notebook took the branch that deletes the key, and the long list
// went back to its first page on the next poll. A list outside a notebook
// has one instance and keeps its plain key.
function pageKey(host, name){
  const nb = host.closest?.(".nb")?.dataset.project;
  return (nb ? nb + ":" : "") + (name || host.id);
}

// How many of a long list's rows to build: the pages shown so far (the
// operator, 17 Oct: a list of 795 bugs built every row on each press and
// hid all but 25, three seconds on a phone). The caller builds that many
// and hands paginate `total` and `more`, which builds the next page.
function pageLimit(host, name, total, size = PAGE){
  const key = pageKey(host, name);
  if (total <= size + 5){ delete pageState[key]; return total; }
  return Math.min(total, size * Math.max(pageState[key] || 1, 1));
}

function paginate(host, rowSel, opts = {}){
  if (!host) return;
  const key = pageKey(host, opts.key);
  const rows = [...host.querySelectorAll(rowSel)];
  const old = host.querySelector(":scope > .pagemore");
  if (old){ old.__io?.disconnect(); old.remove(); }
  const size = opts.size || PAGE;
  // Built a page at a time (pageLimit): the rows here are all that is built,
  // `total` how many there are, and `more` builds the next page.
  if (opts.total !== undefined && opts.more){
    rows.forEach(r => r.hidden = false);
    if (rows.length >= opts.total) return;
    const bar = document.createElement("div");
    bar.className = "pagemore";
    bar.innerHTML = `<span>${rows.length} of ${opts.total}${opts.noun ? " " + esc(opts.noun) : ""}</span>
      <button type="button" class="next">Show more</button>`;
    const more = () => {
      if (!bar.isConnected) return;
      bar.__io?.disconnect();
      pageState[key] = Math.ceil(rows.length / size) + 1;
      opts.more();
    };
    bar.querySelector(".next").addEventListener("click", more);
    if (typeof IntersectionObserver === "function"){
      bar.__io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) more(); }, {rootMargin: "0px 0px 120px 0px"});
      requestAnimationFrame(() => bar.isConnected && bar.__io.observe(bar));
    }
    host.appendChild(bar);
    return;
  }
  // A list that only just crosses the line is worse cut than whole.
  if (rows.length <= size + 5){
    rows.forEach(r => r.hidden = false);
    delete pageState[key];
    return;
  }
  // Clamped to the list: one that shrank under a poll shows what it has.
  const shown = Math.min(rows.length, size * Math.max(pageState[key] || 1, 1));
  rows.forEach((r, i) => { r.hidden = i >= shown; });
  if (shown >= rows.length) return;
  const bar = document.createElement("div");
  bar.className = "pagemore";
  bar.innerHTML = `<span>${shown} of ${rows.length}${opts.noun ? " " + esc(opts.noun) : ""}</span>
    <button type="button" class="next">Show more</button>`;
  const more = () => {
    if (!bar.isConnected) return;
    pageState[key] = Math.ceil(shown / size) + 1;
    paginate(host, rowSel, opts);
  };
  bar.querySelector(".next").addEventListener("click", more);
  // ...and by itself, as the foot comes into view: a page's worth of rows
  // under the reader, which a short screen may take again at once.
  if (typeof IntersectionObserver === "function"){
    bar.__io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) more(); }, {rootMargin: "0px 0px 120px 0px"});
    requestAnimationFrame(() => bar.isConnected && bar.__io.observe(bar));
  }
  host.appendChild(bar);
}
