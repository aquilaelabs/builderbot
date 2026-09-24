// Long lists, a page at a time: the same number of rows on screen whichever
// page is open, and Previous and Next to move between them, so a list never
// grows down the page under the reader (it used to: a Show more that added
// a page below the last one, until the footer was a screen away from the
// head). The order still means something (bugs by severity, the roadmap in
// the order the work has to happen in), so a page is named by the rows it
// holds, "26 to 50 of 80 bugs", and never by a number.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

const PAGE = 25;

const pageState = {};      // list id -> the page that is open, from 1

function paginate(host, rowSel, opts = {}){
  if (!host) return;
  // The notebook this list is in, folded into the key. A notebook is a CLONE
  // of one template, so every id inside it is shared by every open notebook,
  // and a key of "artList" was one bucket for all of them. The visible effect
  // was paging appearing not to work: a SHORT list in another notebook
  // takes the `rows.length <= size + 5` branch, which deletes the key, and
  // the long list snapped back to its first page on the next poll: within a
  // second or two of the click, which reads as the button doing nothing.
  // A list outside a notebook has one instance and keeps its plain key.
  const nb = host.closest?.(".nb")?.dataset.project;
  const key = (nb ? nb + ":" : "") + (opts.key || host.id);
  const rows = [...host.querySelectorAll(rowSel)];
  host.querySelector(":scope > .pagemore")?.remove();
  const size = opts.size || PAGE;
  // A list that only just crosses the line is worse paginated than whole:
  // one row on a page of its own is a click to see nothing much.
  if (rows.length <= size + 5){
    rows.forEach(r => r.hidden = false);
    delete pageState[key];
    return;
  }
  // Clamped: a list that shrank under a poll while its last page was open
  // shows its new last page rather than an empty one.
  const pages = Math.ceil(rows.length / size);
  const cur = Math.min(Math.max(pageState[key] || 1, 1), pages);
  const first = (cur - 1) * size, last = Math.min(first + size, rows.length);
  rows.forEach((r, i) => { r.hidden = i < first || i >= last; });
  const bar = document.createElement("div");
  bar.className = "pagemore";
  // A button is offered only where there is a page for it to go to: a
  // Previous on the first page is a control that does nothing.
  bar.innerHTML = `<span>${first + 1} to ${last} of ${rows.length}${
      opts.noun ? " " + esc(opts.noun) : ""}</span>
    ${cur > 1 ? `<button type="button" class="prev">Previous</button>` : ""}
    ${cur < pages ? `<button type="button" class="next">Next</button>` : ""}`;
  const go = n => {
    pageState[key] = n;
    paginate(host, rowSel, opts);
    // The new page starts where the old one did, so the reader is at its
    // top and not at the footer they pressed: nearest, so a list already
    // wholly on screen does not move.
    host.querySelector(rowSel + ":not([hidden])")?.scrollIntoView({block: "nearest"});
  };
  bar.querySelector(".prev")?.addEventListener("click", () => go(cur - 1));
  bar.querySelector(".next")?.addEventListener("click", () => go(cur + 1));
  host.appendChild(bar);
}
