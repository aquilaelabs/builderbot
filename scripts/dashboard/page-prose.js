// One line of prose, in a box that can show all of it: a
// textarea.proseline wraps and grows to its content, and Enter never
// inserts a newline in it. The observer that wires one as it appears runs
// at load, in index.html.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- proselines: one line of prose, in a box that can show all of it ------

// An <input> shows about thirty characters at phone width. A roadmap item, a
// bug's title, a changelog entry or a test's reason runs to three hundred, so
// on a phone every one of those was a field you could not read what you were
// editing in. A `textarea.proseline` wraps and grows to its content instead.
//
// It is still ONE LINE of prose: Enter never inserts a newline here, and a
// site's own Enter handler (add it, save it) still runs, because this only
// prevents the default.
function proseline(el){
  if (!el || el.dataset.prose) return;
  el.dataset.prose = "1";
  const fit = () => { el.style.height = "auto";
                      el.style.height = (el.scrollHeight + 2) + "px"; };
  el.addEventListener("input", fit);
  el.addEventListener("keydown", e => { if (e.key === "Enter") e.preventDefault(); });
  // Twice: once now, and once after layout, because a box that is drawn into
  // a hidden or just-inserted parent measures zero and would stay one line.
  fit();
  requestAnimationFrame(fit);
  // ...and again whenever its WIDTH changes: one drawn while its view was
  // hidden (a notebook opened on a phone, behind the terminal) measured zero
  // both times and stayed two pixels tall until somebody typed in it.
  let w = el.offsetWidth;
  new ResizeObserver(() => { if (el.offsetWidth !== w){ w = el.offsetWidth; fit(); } }).observe(el);
}
// Every proseline in `root`, and `root` itself if it is one.
function proselines(root){
  if (!root) return;
  if (root.matches && root.matches("textarea.proseline")) proseline(root);
  if (root.querySelectorAll)
    root.querySelectorAll("textarea.proseline").forEach(proseline);
}
