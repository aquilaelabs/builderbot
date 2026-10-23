// The page's questions: one modal for every one of them (R121, the operator,
// 23 Oct), in place of the browser's confirm and prompt, whose OK and
// Cancel said yes and no for questions that had other answers ("OK copies
// it, Cancel leaves it" was the storage move's). The house dialog
// (a-dialog): `.modal > .box`, its h3 the question, what follows it in
// `.field` bands, the foot's verbs in words, the primary first and anything
// destructive last; Escape and a press on the backdrop are Cancel.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

let askSeq = 0;

// ask({title, text, choices, cancel}): the value of the choice pressed, or
// null for Cancel, Escape or the backdrop. `choices` are [{label, value,
// danger}], the first the primary; `title` defaults to the text's first
// paragraph, the rest being its body. `field` asks for a line of text as
// well ({value, label}), and the answer is then {value, text}.
function ask({title = "", text = "", choices = [{label: "Yes", value: true}], cancel = "Cancel", field = null} = {}){
  const paras = String(text || "").split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  const head = title || paras.shift() || "";
  const danger = choices.some(c => c.danger);
  return new Promise(resolve => {
    const id = `ask${++askSeq}`;
    const m = document.createElement("div");
    m.className = "modal askdlg";
    m.setAttribute("role", "dialog");
    m.setAttribute("aria-modal", "true");
    m.setAttribute("aria-labelledby", `${id}T`);
    m.hidden = true;
    const btn = (c, i) => `<button type="button" data-ai="${i}" class="${
      [i === 0 && !c.danger ? "primary" : "", c.danger ? "danger" : ""].filter(Boolean).join(" ")}">${esc(c.label)}</button>`;
    const cancelBtn = `<button type="button" data-acancel>${esc(cancel)}</button>`;
    // The primary first and anything destructive last: a question whose
    // answer destroys something puts Cancel before it.
    const verbs = choices.map(btn).join("");
    m.innerHTML = `<div class="box">
      <h3 id="${id}T">${esc(head)}</h3>
      ${paras.map(p => `<div class="field"><p class="asksaid">${esc(p).replace(/\n/g, "<br>")}</p></div>`).join("")}
      ${field ? `<div class="field">${field.label ? `<label for="${id}F">${esc(field.label)}</label>` : ""}
        <input id="${id}F" data-afield value="${esc(field.value || "")}" spellcheck="false" autocomplete="off"
          aria-label="${esc(field.label || head)}"></div>` : ""}
      <div class="foot"><span class="sp"></span>${danger ? cancelBtn + verbs : verbs + cancelBtn}</div>
    </div>`;
    document.body.appendChild(m);
    armModal(m);
    let over = false;
    const done = v => {
      if (over) return;
      over = true;
      m.hidden = true;
      setTimeout(() => m.remove(), 400);
      resolve(v);
    };
    const value = i => field ? {value: choices[i].value, text: m.querySelector("[data-afield]").value} : choices[i].value;
    // A press on the backdrop is Cancel, and so is Escape, which the
    // page's one dialog keydown (modalKeys) sends here as a backdrop press.
    m.onclick = e => { if (e.target === m) done(null); };
    m.querySelector("[data-acancel]").onclick = () => done(null);
    m.querySelectorAll("[data-ai]").forEach(b => b.onclick = () => done(value(+b.dataset.ai)));
    if (field) m.querySelector("[data-afield]").onkeydown = e => {
      if (e.key === "Enter"){ e.preventDefault(); done(value(0)); }
    };
    m.hidden = false;
    requestAnimationFrame(() => (field ? m.querySelector("[data-afield]") : m.querySelector(danger ? "[data-acancel]" : '[data-ai="0"]'))?.focus());
    // The test harness answers a question as it answered the browser's
    // (lib.mjs): it is told the words and says which button to press, a
    // choice's index or -1 for Cancel, and the press is made on the modal.
    if (typeof window.__bbAsk === "function"){
      Promise.resolve(window.__bbAsk({title: head, text: String(text || ""), choices: choices.map(c => c.label)}))
        .then(i => requestAnimationFrame(() => {
          if (field && typeof i === "object" && i){ m.querySelector("[data-afield]").value = i.text ?? ""; i = i.index ?? 0; }
          const b = i === -1 || i === null ? m.querySelector("[data-acancel]") : m.querySelector(`[data-ai="${i ?? 0}"]`);
          (b || m.querySelector("[data-acancel]")).click();
        }));
    }
  });
}

// What a question's yes is called: its own verb where it opens with one
// ("Archive alpha?" is Archive), else Yes. A question that asks rather
// than proposes (Is, Use the, Should) is a Yes.
const ASK_NOT_VERBS = new Set(["is", "are", "do", "does", "did", "should", "will", "would", "can", "could",
                               "may", "has", "have", "was", "were", "this", "that", "the", "a", "an", "your"]);
function askYesWord(text){
  const first = String(text || "").trim().split(/\n/)[0];
  const w = (first.match(/^([A-Z][a-z]+)\b/) || [])[1] || "";
  return first.endsWith("?") && w && !ASK_NOT_VERBS.has(w.toLowerCase()) ? w : "Yes";
}

// The verbs that cannot be taken back, which wear .danger and come after
// Cancel (a-dialog: anything destructive last).
const ASK_DANGER = new Set(["Delete", "Remove", "End", "Uninstall", "Discard", "Retire", "Reset", "Forget",
                            "Purge", "Wipe", "Unenroll", "Kill", "Drop", "Clear", "Stop", "Revoke",
                            "Overwrite", "Replace", "Rotate", "Destroy", "Erase", "Unlink", "Abandon"]);

// confirm()'s replacement: true for its yes, false for Cancel. `verb` names
// the yes (askYesWord by default), `danger` marks it destructive, as a verb in
// ASK_DANGER is by itself.
async function askYes(text, {verb = "", danger = false, title = ""} = {}){
  const v = verb || askYesWord(title || text);
  return (await ask({title, text, choices: [{label: v, value: true, danger: danger || ASK_DANGER.has(v)}]})) === true;
}

// prompt()'s replacement: the text typed, or null for Cancel.
async function askText(text, {value = "", verb = "OK", label = ""} = {}){
  const got = await ask({text, choices: [{label: verb, value: true}], field: {value, label}});
  return got ? got.text : null;
}
