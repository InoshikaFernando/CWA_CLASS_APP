/*
 * table_of_values.js — interactive "fill in the x/y table" tool.
 *
 * Dependency-free. Mounts on every `[data-tv-stage]`: each blank cell
 * (`[data-tv-cell]`, carrying its "row,col" key in data-rc) is collected into
 * the stage's hidden input as JSON {"cells":{"r,c":"value"}}. Given cells are
 * static text and need no wiring.
 *
 * Idempotent (a `data-tv-mounted` flag guards re-mounts) and re-scans on
 * DOMContentLoaded AND via a MutationObserver, because the topic quiz and the
 * worksheet session swap questions in with innerHTML (inline scripts would not
 * run). Each stage is scoped to its own element, so any number of table
 * questions can share a page. Reads the hidden input's current value on mount,
 * so a restored/resumed draft re-fills correctly.
 */
(function () {
  "use strict";

  function mount(stage) {
    if (!stage || stage.dataset.tvMounted === "1") return;
    var hidden = stage.querySelector("[data-tv-hidden]");
    var cells = stage.querySelectorAll("[data-tv-cell]");
    if (!hidden || !cells.length) return;
    stage.dataset.tvMounted = "1";

    function refresh() {
      var out = {};
      cells.forEach(function (el) {
        var v = (el.value || "").trim();
        if (v !== "") out[el.dataset.rc] = v;
      });
      hidden.value = JSON.stringify({ cells: out });
    }

    cells.forEach(function (el) {
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
      el.addEventListener("blur", refresh);
    });
    var form = stage.closest("form");
    if (form) form.addEventListener("submit", refresh, true);

    // Rehydrate from a saved/resumed value, then keep the hidden field in sync.
    try {
      var saved = JSON.parse(hidden.value || "{}");
      if (saved && saved.cells) {
        cells.forEach(function (el) {
          if (saved.cells[el.dataset.rc] != null) el.value = saved.cells[el.dataset.rc];
        });
      }
    } catch (e) { /* malformed saved value — start blank */ }
    refresh();
  }

  function scan(root) {
    (root || document).querySelectorAll("[data-tv-stage]").forEach(mount);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { scan(document); });
  } else {
    scan(document);
  }

  if (typeof MutationObserver !== "undefined") {
    var obs = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        if (muts[i].addedNodes && muts[i].addedNodes.length) { scan(document); break; }
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  }
})();
