// Long lists, shown a page at a time: not numbered pages, since these lists
// are read in an order that means something (bugs by severity, the roadmap
// in the order the work has to happen in); a page of rows and a control
// that adds another keeps the order and the browser's own find working.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

const PAGE = 25;

const pageState = {};      // list id -> how many rows are currently shown

function paginate(host, rowSel, opts = {}){
  if (!host) return;
  // The notebook this list is in, folded into the key. A notebook is a CLONE
  // of one template, so every id inside it is shared by every open notebook,
  // and a key of "artList" was one bucket for all of them. The visible effect
  // was Show more appearing not to work: a SHORT list in another notebook
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
  // one hidden row behind a button is a click to see nothing much.
  if (rows.length <= size + 5){
    rows.forEach(r => r.hidden = false);
    delete pageState[key];
    return;
  }
  const shown = Math.min(pageState[key] || size, rows.length);
  rows.forEach((r, i) => { r.hidden = i >= shown; });
  const left = rows.length - shown;
  const bar = document.createElement("div");
  bar.className = "pagemore";
  // With nothing left there is no "more" to offer: a "Show 0 more" button is
  // a control that does nothing, and the count alone is the honest footer.
  bar.innerHTML = `<span>${left ? `${shown} of ${rows.length}` : `all ${rows.length}`}${
      opts.noun ? " " + esc(opts.noun) : ""}</span>
    ${left ? `<button type="button" class="more">Show ${
      Math.min(size, left)} more</button>` : ""}
    ${left > size ? `<button type="button" class="all">Show all</button>` : ""}
    ${shown > size ? `<button type="button" class="fewer">Fewer</button>` : ""}`;
  bar.querySelector(".more")?.addEventListener("click", () => {
    pageState[key] = shown + size; paginate(host, rowSel, opts);
  });
  bar.querySelector(".all")?.addEventListener("click", () => {
    pageState[key] = rows.length; paginate(host, rowSel, opts);
  });
  bar.querySelector(".fewer")?.addEventListener("click", () => {
    pageState[key] = size; paginate(host, rowSel, opts);
    host.scrollIntoView({block: "nearest"});
  });
  host.appendChild(bar);
}
